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


def _item(monto, modo="contado", desc="Juego | Licencia | PS5"):
    return {"modo_pago": modo, "descripcion": desc, "monto": monto}


def _tx():
    return SimpleNamespace(pk=5, id_invoice="inv_1_abc")


class UmbralTest(SimpleTestCase):
    def _registrar(self, items, env=ENV):
        with mock.patch.dict(os.environ, env, clear=False), \
                mock.patch.object(alegra.AlegraInvoice.objects, "get_or_create",
                                  return_value=(SimpleNamespace(pk=1), True)) as goc, \
                mock.patch.object(alegra.threading, "Thread") as thread:
            alegra.registrar_venta(_tx(), items)
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
    def _inv(self, email):
        return SimpleNamespace(alegra_id="9", transaction=SimpleNamespace(user_id=SimpleNamespace(email=email)))

    def _enviar(self, email, env=ENV):
        with mock.patch.dict(os.environ, env),                 mock.patch.object(alegra.requests, "post", return_value=mock.Mock(status_code=200)) as post:
            alegra._enviar_por_correo(self._inv(email))
        return post

    def test_correo_valido_se_usa(self):
        self.assertEqual(self._enviar("a@b.com").call_args.kwargs["json"]["emails"], ["a@b.com"])

    def test_correo_invalido_usa_el_ficticio(self):
        env = {**ENV, "ALEGRA_FALLBACK_EMAIL": "facturas@ejemplo.co"}
        self.assertEqual(self._enviar("no-es-correo", env).call_args.kwargs["json"]["emails"], ["facturas@ejemplo.co"])

    def test_correo_invalido_sin_ficticio_no_envia(self):
        with mock.patch.dict(os.environ, {k: v for k, v in ENV.items()}),                 mock.patch.dict(os.environ, {"ALEGRA_FALLBACK_EMAIL": ""}):
            self.assertFalse(self._enviar("roto").called)
