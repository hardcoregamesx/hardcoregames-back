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
        self.assertEqual(p["items"], [{"id": 7, "description": "A", "price": 120000, "quantity": 1}])
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
                mock.patch.object(alegra, "_enviar_por_correo") as correo:
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
    def _inv(self, email, request=None):
        return SimpleNamespace(alegra_id="9", transaction=SimpleNamespace(
            request=request, user_id=SimpleNamespace(email=email)))

    def _enviar(self, email, env=ENV, request=None):
        with mock.patch.dict(os.environ, env),                 mock.patch.object(alegra.requests, "post", return_value=mock.Mock(status_code=200)) as post:
            alegra._enviar_por_correo(self._inv(email, request))
        return post

    def test_el_correo_de_facturacion_tiene_prioridad(self):
        req = json.dumps({"facturacion": {**FACT, "email": "fact@x.co"}})
        self.assertEqual(self._enviar("cuenta@x.co", request=req).call_args.kwargs["json"]["emails"], ["fact@x.co"])

    def test_correo_valido_se_usa(self):
        self.assertEqual(self._enviar("a@b.com").call_args.kwargs["json"]["emails"], ["a@b.com"])

    def test_correo_invalido_usa_el_ficticio(self):
        env = {**ENV, "ALEGRA_FALLBACK_EMAIL": "facturas@ejemplo.co"}
        self.assertEqual(self._enviar("no-es-correo", env).call_args.kwargs["json"]["emails"], ["facturas@ejemplo.co"])

    def test_correo_invalido_sin_ficticio_no_envia(self):
        with mock.patch.dict(os.environ, {k: v for k, v in ENV.items()}),                 mock.patch.dict(os.environ, {"ALEGRA_FALLBACK_EMAIL": ""}):
            self.assertFalse(self._enviar("roto").called)



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
