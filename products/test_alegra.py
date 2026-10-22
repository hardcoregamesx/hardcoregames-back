import json
import os
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from products import alegra
from products.models import AlegraInvoice

ENV = {
    "ALEGRA_ENABLED": "1",
    "ALEGRA_TOKEN": "tok",
    "ALEGRA_ITEM_ID": "7",
    "ALEGRA_MODE": "draft",
}


FACT = {"tipo_doc": "CC", "numero": "1.114.456.688", "nombre": "  Juan  Carlos ", "apellidos": " Perez  Gomez", "email": "j@x.co"}


def _item(monto, modo="contado", desc="Juego | Licencia | PS5"):
    return {"modo_pago": modo, "descripcion": desc, "monto": monto}


def _tx():
    return SimpleNamespace(pk=5, id_invoice="inv_1_abc", request=None)


class UmbralTest(SimpleTestCase):
    def _registrar(self, items, env=ENV, facturacion=None):
        with mock.patch.dict(os.environ, env, clear=False), \
                mock.patch.object(alegra.AlegraInvoice.objects, "get_or_create",
                                  return_value=(SimpleNamespace(pk=1), True)) as goc, \
                mock.patch.object(alegra.threading, "Thread") as thread:
            alegra.registrar_venta(_tx(), items, facturacion)
            return goc.called, thread.called

    def test_exactamente_el_umbral_no_se_factura(self):
        self.assertEqual(self._registrar([_item(99980)]), (False, False))

    def test_un_peso_arriba_si_se_factura(self):
        self.assertEqual(self._registrar([_item(99981)]), (True, True))

    def test_carrito_suma_todas_las_lineas(self):
        self.assertEqual(self._registrar([_item(60000), _item(50000)]), (True, True))

    def test_cuotas_y_reserva_no_cuentan(self):
        self.assertEqual(self._registrar([_item(500000, modo="cuotas"), _item(500000, modo="reserva")]),
                         (False, False))

    def test_apagado_no_hace_nada(self):
        self.assertEqual(self._registrar([_item(500000)], env={**ENV, "ALEGRA_ENABLED": "0"}), (False, False))

    def test_sin_transaccion_no_hace_nada(self):
        with mock.patch.dict(os.environ, ENV):
            self.assertIsNone(alegra.registrar_venta(None, [_item(500000)]))

    def test_nunca_lanza_si_la_base_falla(self):
        with mock.patch.dict(os.environ, ENV), \
                mock.patch.object(alegra.AlegraInvoice.objects, "get_or_create", side_effect=Exception("db caida")):
            self.assertIsNone(alegra.registrar_venta(_tx(), [_item(500000)]))

    def test_umbral_configurable(self):
        self.assertEqual(self._registrar([_item(60000)], env={**ENV, "ALEGRA_MIN_AMOUNT": "50000"}), (True, True))


class PayloadTest(SimpleTestCase):
    def test_borrador_por_defecto(self):
        with mock.patch.dict(os.environ, ENV):
            p = alegra.construir_payload(_tx(), [{"descripcion": "A", "monto": 120000}])
        self.assertEqual(p["status"], "draft")
        self.assertNotIn("stamp", p)
        self.assertEqual(p["client"], {"id": 1})
        self.assertEqual(p["numberTemplate"], {"id": 15})
        self.assertEqual(p["items"], [{"id": 7, "reference": "HG-DIGITAL", "description": "A", "price": 120000, "quantity": 1}])
        self.assertNotIn("tax", p["items"][0])

    def test_modo_stamp_emite_a_la_dian(self):
        with mock.patch.dict(os.environ, {**ENV, "ALEGRA_MODE": "stamp"}):
            p = alegra.construir_payload(_tx(), [{"descripcion": "A", "monto": 120000}])
        self.assertEqual(p["status"], "open")
        self.assertEqual(p["stamp"], {"generateStamp": True})


class ProcesarTest(SimpleTestCase):
    def _inv(self, intentos=0):
        inv = mock.MagicMock()
        inv.estado = AlegraInvoice.ESTADO_PENDIENTE
        inv.intentos = intentos
        inv.pk = 1
        inv.transaction_id = 5
        inv.monto = 120000
        inv.items_json = json.dumps([{"descripcion": "A", "monto": 120000}])
        inv.transaction = _tx()
        return inv

    def _run(self, inv, response=None, post_error=None, env=ENV):
        qs = mock.MagicMock()
        qs.select_related.return_value.filter.return_value.first.return_value = inv
        with mock.patch.dict(os.environ, env), \
                mock.patch.object(alegra.AlegraInvoice.objects, "select_for_update", return_value=qs), \
                mock.patch.object(alegra.db_transaction, "atomic"), \
                mock.patch.object(alegra.requests, "post", side_effect=post_error, return_value=response) as post, \
                mock.patch.object(alegra, "_avisar_fallo") as aviso, \
                mock.patch.object(alegra, "_notificar_comprador") as correo:
            alegra.procesar(1)
        return post, aviso, correo

    def test_exito_en_borrador(self):
        resp = mock.Mock(status_code=201, json=lambda: {"id": 99, "numberTemplate": {"prefix": "HG", "number": "12"}})
        inv = self._inv()
        _, aviso, correo = self._run(inv, response=resp)
        self.assertEqual((inv.estado, inv.alegra_id, inv.numero), ("borrador", "99", "HG12"))
        aviso.assert_not_called()
        correo.assert_not_called()

    def test_exito_emitida_envia_correo(self):
        resp = mock.Mock(status_code=201, json=lambda: {"id": 99, "numberTemplate": {"prefix": "HG", "number": "12"}})
        inv = self._inv()
        _, _, correo = self._run(inv, response=resp, env={**ENV, "ALEGRA_MODE": "stamp"})
        self.assertEqual(inv.estado, "emitida")
        correo.assert_called_once()

    def test_fallo_deja_pendiente_para_reintento(self):
        inv = self._inv(intentos=0)
        _, aviso, _ = self._run(inv, response=mock.Mock(status_code=503, text="caido"))
        self.assertEqual(inv.estado, AlegraInvoice.ESTADO_PENDIENTE)
        self.assertEqual(inv.intentos, 1)
        self.assertIn("503", inv.ultimo_error)
        aviso.assert_not_called()

    def test_timeout_deja_pendiente(self):
        inv = self._inv()
        self._run(inv, post_error=alegra.requests.Timeout("lento"))
        self.assertEqual(inv.estado, AlegraInvoice.ESTADO_PENDIENTE)

    def test_agotar_intentos_marca_fallida_y_avisa(self):
        inv = self._inv(intentos=4)
        _, aviso, _ = self._run(inv, response=mock.Mock(status_code=400, text="mal"))
        self.assertEqual(inv.estado, AlegraInvoice.ESTADO_FALLIDA)
        aviso.assert_called_once()

    def test_ya_procesada_no_vuelve_a_facturar(self):
        inv = self._inv()
        inv.estado = AlegraInvoice.ESTADO_EMITIDA
        post, _, _ = self._run(inv, response=mock.Mock(status_code=201))
        post.assert_not_called()


class MedioDePagoTest(SimpleTestCase):
    def _m(self, pid):
        return alegra.metodo_pago(SimpleNamespace(payment_id=pid))

    def test_tarjetas(self):
        for pid in ("VISA", "MASTERCARD", "AMEX", "CARD"):
            self.assertEqual(self._m(pid), "CREDIT_CARD", pid)

    def test_transferencias_y_pse(self):
        for pid in ("PSE", "transferencia_brebb", "NEQUI", "BOTON_BANCOLOMBIA"):
            self.assertEqual(self._m(pid), "DEBIT_TRANSFER", pid)

    def test_sistecredito(self):
        self.assertEqual(self._m("sistecredito"), "CREDIT_TRANSFER")

    def test_desconocido_o_vacio_cae_en_cash(self):
        for pid in ("", None, "algo_raro"):
            self.assertEqual(self._m(pid), "CASH", pid)

    def test_payload_usa_el_medio_real(self):
        with mock.patch.dict(os.environ, ENV):
            tx = SimpleNamespace(pk=1, id_invoice="x", payment_id="PSE")
            p = alegra.construir_payload(tx, [{"descripcion": "A", "monto": 120000}])
        self.assertEqual((p["paymentForm"], p["paymentMethod"]), ("CASH", "DEBIT_TRANSFER"))


class CorreoTest(SimpleTestCase):
    """Alegra envía sola la factura a clientes con datos; a Consumidor Final la envía la tienda."""

    def _inv(self, email, request=None):
        return SimpleNamespace(alegra_id="9", numero="HG17", monto=120000,
                               items_json=json.dumps([{"descripcion": "Juego | PS5", "monto": 120000}]),
                               transaction=SimpleNamespace(request=request, user_id=SimpleNamespace(email=email)))

    API = {"date": "2026-10-22", "stamp": {"cufe": "abc123"}, "xml": "https://s3/factura.xml",
           "numberTemplate": {"fullNumber": "HG17"}}

    def _notificar(self, email, env=ENV, request=None, api=None):
        get = mock.Mock(side_effect=[mock.Mock(status_code=200, json=lambda: api or self.API, raise_for_status=lambda: None),
                                     mock.Mock(ok=True, content=b"<xml/>")])
        with mock.patch.dict(os.environ, env), mock.patch.object(alegra.requests, "get", get),                 mock.patch.object(alegra, "_enviar_correo_factura") as enviar:
            alegra._notificar_comprador(self._inv(email, request))
        return enviar

    def test_consumidor_final_recibe_la_factura_de_la_tienda(self):
        e = self._notificar("comprador@x.co")
        e.assert_called_once()
        destino, numero, monto, fecha, items, cufe, xml = e.call_args.args
        self.assertEqual((destino, numero, monto, cufe, xml), ("comprador@x.co", "HG17", 120000, "abc123", b"<xml/>"))

    def test_cliente_con_datos_no_recibe_duplicado_porque_alegra_ya_se_la_envia(self):
        req = json.dumps({"facturacion": FACT})
        with mock.patch.dict(os.environ, ENV), mock.patch.object(alegra.requests, "get") as get,                 mock.patch.object(alegra, "_enviar_correo_factura") as enviar:
            alegra._notificar_comprador(self._inv("cuenta@x.co", req))
        get.assert_not_called()
        enviar.assert_not_called()

    def test_correo_invalido_usa_el_alterno(self):
        env = {**ENV, "ALEGRA_FALLBACK_EMAIL": "facturas@ejemplo.co"}
        self.assertEqual(self._notificar("no-es-correo", env).call_args.args[0], "facturas@ejemplo.co")

    def test_correo_invalido_sin_alterno_no_envia(self):
        with mock.patch.dict(os.environ, {**ENV, "ALEGRA_FALLBACK_EMAIL": ""}),                 mock.patch.object(alegra.requests, "get") as get,                 mock.patch.object(alegra, "_enviar_correo_factura") as enviar:
            alegra._notificar_comprador(self._inv("roto"))
        get.assert_not_called()
        enviar.assert_not_called()

    def test_no_usa_el_endpoint_de_correo_de_alegra_que_el_token_no_permite(self):
        with mock.patch.dict(os.environ, ENV), mock.patch.object(alegra.requests, "post") as post:
            self._notificar("a@b.com")
        post.assert_not_called()

    def test_si_el_xml_no_se_puede_bajar_el_correo_sale_igual_sin_adjunto(self):
        get = mock.Mock(side_effect=[mock.Mock(status_code=200, json=lambda: self.API, raise_for_status=lambda: None),
                                     alegra.requests.ConnectionError("dns")])
        with mock.patch.dict(os.environ, ENV), mock.patch.object(alegra.requests, "get", get),                 mock.patch.object(alegra, "_enviar_correo_factura") as enviar:
            alegra._notificar_comprador(self._inv("comprador@x.co"))
        enviar.assert_called_once()
        self.assertEqual(enviar.call_args.args[6], b"")  # sin xml
        self.assertEqual(enviar.call_args.args[5], "abc123")  # pero con CUFE

    def test_si_algo_falla_no_lanza(self):
        with mock.patch.dict(os.environ, ENV), mock.patch.object(alegra.requests, "get", side_effect=Exception("red")):
            alegra._notificar_comprador(self._inv("a@b.com"))  # no debe lanzar

    def test_el_correo_incluye_cufe_enlace_de_la_dian_y_xml_adjunto(self):
        smtp = mock.MagicMock()
        with mock.patch.object(alegra.smtplib, "SMTP_SSL", return_value=smtp),                 mock.patch.object(alegra.settings, "FROM_EMAIL", "tienda@x.co", create=True),                 mock.patch.object(alegra.settings, "PASS_SMTP", "pw", create=True):
            alegra._enviar_correo_factura("c@x.co", "HG17", 120000, "2026-10-22",
                                          [{"descripcion": "Juego <PS5>", "monto": 120000}], "abc123", b"<xml/>")
        msg = smtp.send_message.call_args.args[0]
        cuerpo = msg.get_body(("html",)).get_content()
        self.assertEqual((msg["To"], msg["Subject"]), ("c@x.co", "Tu factura electrónica HG17 - Hardcore Games"))
        self.assertIn("$120.000", cuerpo)
        self.assertIn("documentkey=abc123", cuerpo)
        self.assertIn("1114456688-9", cuerpo)  # el NIT del emisor que pide el formulario de la DIAN
        self.assertIn("CUFE: abc123", cuerpo)
        self.assertIn("&lt;PS5&gt;", cuerpo)  # el texto del producto se escapa
        adjuntos = [part.get_filename() for part in msg.iter_attachments()]
        self.assertEqual(adjuntos, ["HG17.xml"])
        smtp.quit.assert_called_once()


class ReferenciaPorLineaTest(SimpleTestCase):
    def test_cada_linea_lleva_el_codigo_del_producto(self):
        with mock.patch.dict(os.environ, ENV):
            p = alegra.construir_payload(_tx(), [{"descripcion": "A", "monto": 1}, {"descripcion": "B", "monto": 2}])
        self.assertEqual([i["reference"] for i in p["items"]], ["HG-DIGITAL", "HG-DIGITAL"])

    def test_el_codigo_se_puede_configurar_y_se_recorta_a_45(self):
        with mock.patch.dict(os.environ, {**ENV, "ALEGRA_ITEM_REFERENCE": "X" * 80}):
            p = alegra.construir_payload(_tx(), [{"descripcion": "A", "monto": 1}])
        self.assertEqual(len(p["items"][0]["reference"]), 45)


class FacturacionDatosTest(SimpleTestCase):
    def test_normaliza_y_limpia(self):
        self.assertEqual(alegra.normalizar_facturacion(FACT),
                         {"tipo_doc": "CC", "numero": "1114456688", "nombre": "Juan Carlos",
                          "apellidos": "Perez Gomez", "email": "j@x.co"})

    def test_datos_invalidos_devuelven_none(self):
        for malo in (None, "x", {}, {**FACT, "tipo_doc": "XX"}, {**FACT, "numero": "12"},
                     {**FACT, "numero": "abc"}, {**FACT, "nombre": "a"},
                     {**FACT, "nombre": "Juan", "apellidos": ""}):
            self.assertIsNone(alegra.normalizar_facturacion(malo), malo)

    def test_nombre_en_un_solo_campo_separa_el_ultimo_como_apellido(self):
        r = alegra.normalizar_facturacion({**FACT, "nombre": "Juan Carlos Perez", "apellidos": ""})
        self.assertEqual((r["nombre"], r["apellidos"]), ("Juan Carlos", "Perez"))

    def test_nit_usa_razon_social_y_no_pide_apellidos(self):
        r = alegra.normalizar_facturacion({**FACT, "tipo_doc": "NIT", "numero": "900123456", "nombre": "Mi Empresa SAS", "apellidos": "x"})
        self.assertEqual((r["nombre"], r["apellidos"]), ("Mi Empresa SAS", ""))

    def test_correo_invalido_se_descarta_pero_la_factura_sigue(self):
        self.assertEqual(alegra.normalizar_facturacion({**FACT, "email": "roto"})["email"], "")

    def test_solo_conserva_las_cuatro_claves(self):
        r = alegra.normalizar_facturacion({**FACT, "isAdmin": True, "x": "<script>"})
        self.assertEqual(set(r), {"tipo_doc", "numero", "nombre", "apellidos", "email"})

    def test_facturacion_de_lee_el_json_guardado(self):
        self.assertEqual(alegra.facturacion_de(json.dumps({"facturacion": FACT}))["numero"], "1114456688")
        self.assertIsNone(alegra.facturacion_de("no es json"))
        self.assertIsNone(alegra.facturacion_de(None))


class PidioFacturaTest(SimpleTestCase):
    _registrar = UmbralTest._registrar

    """Con el checkbox marcado se factura aunque no pase el tope; sin eso, el tope manda."""

    def test_pidio_factura_bajo_el_tope_se_factura(self):
        self.assertEqual(self._registrar([_item(30000)], facturacion=FACT), (True, True))

    def test_no_pidio_factura_bajo_el_tope_no_se_factura(self):
        self.assertEqual(self._registrar([_item(30000)], facturacion=None), (False, False))

    def test_datos_invalidos_no_cuentan_como_pedido(self):
        self.assertEqual(self._registrar([_item(30000)], facturacion={"tipo_doc": "CC"}), (False, False))

    def test_pidio_factura_pero_no_es_de_contado_no_se_factura(self):
        self.assertEqual(self._registrar([_item(30000, modo="cuotas")], facturacion=FACT), (False, False))


class ClienteAlegraTest(SimpleTestCase):
    F = alegra.normalizar_facturacion(FACT)

    def test_sin_datos_es_consumidor_final(self):
        with mock.patch.dict(os.environ, ENV):
            self.assertEqual(alegra.cliente_alegra(None), 1)

    def test_reusa_contacto_existente_por_identificacion_exacta(self):
        resp = mock.Mock(status_code=200, json=lambda: [
            {"id": "50", "identification": "11144566880"},  # prefijo: NO debe coincidir
            {"id": "51", "identification": "1114456688", "regime": "SIMPLIFIED_REGIME"},
        ])
        with mock.patch.dict(os.environ, ENV), mock.patch.object(alegra.requests, "get", return_value=resp),                 mock.patch.object(alegra.requests, "post") as post:
            self.assertEqual(alegra.cliente_alegra(self.F), 51)
        post.assert_not_called()

    def test_nit_con_digito_de_verificacion_coincide(self):
        f = alegra.normalizar_facturacion({**FACT, "tipo_doc": "NIT", "numero": "900123456"})
        resp = mock.Mock(status_code=200, json=lambda: [
            {"id": "7", "identification": "900123456-7", "regime": "COMMON_REGIME"}])
        with mock.patch.dict(os.environ, ENV), mock.patch.object(alegra.requests, "get", return_value=resp):
            self.assertEqual(alegra.cliente_alegra(f), 7)

    def test_crea_el_contacto_si_no_existe(self):
        get = mock.Mock(status_code=200, json=lambda: [])
        post = mock.Mock(status_code=201, json=lambda: {"id": "88"})
        with mock.patch.dict(os.environ, ENV), mock.patch.object(alegra.requests, "get", return_value=get),                 mock.patch.object(alegra.requests, "post", return_value=post) as p:
            self.assertEqual(alegra.cliente_alegra(self.F), 88)
        body = p.call_args.kwargs["json"]
        self.assertEqual(body["identificationObject"], {"type": "CC", "number": "1114456688"})
        self.assertEqual((body["kindOfPerson"], body["email"]), ("PERSON_ENTITY", "j@x.co"))
        self.assertEqual(body["nameObject"], {"firstName": "Juan", "secondName": "Carlos",
                                              "lastName": "Perez", "secondLastName": "Gomez"})
        self.assertNotIn("name", body)

    def test_nit_se_crea_como_persona_juridica(self):
        f = alegra.normalizar_facturacion({**FACT, "tipo_doc": "NIT", "numero": "900123456"})
        with mock.patch.dict(os.environ, ENV),                 mock.patch.object(alegra.requests, "get", return_value=mock.Mock(status_code=200, json=lambda: [])),                 mock.patch.object(alegra.requests, "post", return_value=mock.Mock(status_code=201, json=lambda: {"id": "9"})) as p:
            alegra.cliente_alegra(f)
        body = p.call_args.kwargs["json"]
        self.assertEqual((body["kindOfPerson"], body["name"]), ("LEGAL_ENTITY", "Juan Carlos"))
        self.assertNotIn("nameObject", body)

    def test_error_al_crear_contacto_propaga_para_reintentar(self):
        with mock.patch.dict(os.environ, ENV),                 mock.patch.object(alegra.requests, "get", return_value=mock.Mock(status_code=200, json=lambda: [])),                 mock.patch.object(alegra.requests, "post", return_value=mock.Mock(status_code=400, text="mal")):
            with self.assertRaises(RuntimeError):
                alegra.cliente_alegra(self.F)

    def test_payload_usa_el_cliente_indicado(self):
        with mock.patch.dict(os.environ, ENV):
            p = alegra.construir_payload(_tx(), [{"descripcion": "A", "monto": 120000}], client_id=88)
        self.assertEqual(p["client"], {"id": 88})


class RegimenTest(SimpleTestCase):
    """Alegra rechaza la emisión si el contacto con CC no tiene régimen fiscal."""
    F = alegra.normalizar_facturacion(FACT)

    def test_contacto_nuevo_se_crea_con_regimen(self):
        with mock.patch.dict(os.environ, ENV),                 mock.patch.object(alegra.requests, "get", return_value=mock.Mock(status_code=200, json=lambda: [])),                 mock.patch.object(alegra.requests, "post", return_value=mock.Mock(status_code=201, json=lambda: {"id": "8"})) as p:
            alegra.cliente_alegra(self.F)
        self.assertEqual(p.call_args.kwargs["json"]["regime"], "SIMPLIFIED_REGIME")

    def test_empresa_nueva_usa_regimen_comun(self):
        f = alegra.normalizar_facturacion({**FACT, "tipo_doc": "NIT", "numero": "900123456"})
        with mock.patch.dict(os.environ, ENV),                 mock.patch.object(alegra.requests, "get", return_value=mock.Mock(status_code=200, json=lambda: [])),                 mock.patch.object(alegra.requests, "post", return_value=mock.Mock(status_code=201, json=lambda: {"id": "9"})) as p:
            alegra.cliente_alegra(f)
        self.assertEqual(p.call_args.kwargs["json"]["regime"], "COMMON_REGIME")

    def test_contacto_existente_sin_regimen_se_actualiza_con_su_nombre(self):
        viejo = {"id": "7", "identification": "1114456688", "regime": None,
                 "nameObject": {"firstName": "Juan", "secondName": "", "lastName": "Perez", "secondLastName": ""}}
        with mock.patch.dict(os.environ, ENV),                 mock.patch.object(alegra.requests, "get", return_value=mock.Mock(status_code=200, json=lambda: [viejo])),                 mock.patch.object(alegra.requests, "put", return_value=mock.Mock(status_code=200)) as put:
            self.assertEqual(alegra.cliente_alegra(self.F), 7)
        self.assertEqual(put.call_args.args[0], f"{alegra.API_BASE}/contacts/7")
        self.assertEqual(put.call_args.kwargs["json"], {"regime": "SIMPLIFIED_REGIME", "nameObject": viejo["nameObject"]})

    def test_contacto_existente_con_regimen_no_se_toca(self):
        ok = {"id": "7", "identification": "1114456688", "regime": "SIMPLIFIED_REGIME"}
        with mock.patch.dict(os.environ, ENV),                 mock.patch.object(alegra.requests, "get", return_value=mock.Mock(status_code=200, json=lambda: [ok])),                 mock.patch.object(alegra.requests, "put") as put:
            alegra.cliente_alegra(self.F)
        put.assert_not_called()

    def test_si_falla_actualizar_el_regimen_se_propaga_para_reintentar(self):
        viejo = {"id": "7", "identification": "1114456688", "regime": None, "name": "Empresa"}
        with mock.patch.dict(os.environ, ENV),                 mock.patch.object(alegra.requests, "get", return_value=mock.Mock(status_code=200, json=lambda: [viejo])),                 mock.patch.object(alegra.requests, "put", return_value=mock.Mock(status_code=400, text="mal")):
            with self.assertRaises(RuntimeError):
                alegra.cliente_alegra(self.F)


class FacturaHuerfanaTest(SimpleTestCase):
    """Un 400 de emisión deja la factura creada sin emitir: hay que borrarla."""

    def _descartar(self, body):
        resp = mock.Mock(json=lambda: body)
        with mock.patch.dict(os.environ, ENV), mock.patch.object(alegra.requests, "delete") as delete:
            alegra._descartar_factura_huerfana(resp)
        return delete

    def test_borra_la_factura_creada_que_no_se_emitio(self):
        d = self._descartar({"error": {"code": 3051}, "invoice": {"id": "20", "status": "draft"}})
        self.assertEqual(d.call_args.args[0], f"{alegra.API_BASE}/invoices/20")

    def test_nunca_borra_una_factura_ya_emitida(self):
        d = self._descartar({"invoice": {"id": "4", "stamp": {"legalStatus": "STAMPED_AND_ACCEPTED"}}})
        d.assert_not_called()

    def test_sin_factura_en_la_respuesta_no_borra_nada(self):
        self._descartar({"error": {"code": 1}}).assert_not_called()

    def test_si_el_borrado_falla_no_tapa_el_error_original(self):
        resp = mock.Mock(json=lambda: {"invoice": {"id": "9"}})
        with mock.patch.dict(os.environ, ENV), mock.patch.object(alegra.requests, "delete", side_effect=Exception("red")):
            alegra._descartar_factura_huerfana(resp)  # no debe lanzar

    def test_procesar_descarta_la_huerfana_cuando_alegra_responde_400(self):
        inv = ProcesarTest()._inv()
        resp = mock.Mock(status_code=400, text="no cumple", json=lambda: {"invoice": {"id": "20", "status": "draft"}})
        qs = mock.MagicMock()
        qs.select_related.return_value.filter.return_value.first.return_value = inv
        with mock.patch.dict(os.environ, ENV),                 mock.patch.object(alegra.AlegraInvoice.objects, "select_for_update", return_value=qs),                 mock.patch.object(alegra.db_transaction, "atomic"),                 mock.patch.object(alegra.requests, "post", return_value=resp),                 mock.patch.object(alegra.requests, "delete") as delete:
            alegra.procesar(1)
        self.assertEqual(delete.call_args.args[0], f"{alegra.API_BASE}/invoices/20")
        self.assertEqual(inv.estado, AlegraInvoice.ESTADO_PENDIENTE)
