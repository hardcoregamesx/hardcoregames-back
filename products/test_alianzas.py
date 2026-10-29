from datetime import date, datetime
from types import SimpleNamespace

from unittest import TestCase

from products.alianzas import TZ, codigo_del_mes, fin_de_mes, _rango_mes_utc


def _aliado(nombre, secreto, fijo=""):
    return SimpleNamespace(nombre=nombre, secreto=secreto, codigo_fijo=fijo)


class CodigoDelMesTests(TestCase):
    def test_primera_y_ultima_letra_mas_secreto_por_mes(self):
        self.assertEqual(codigo_del_mes(_aliado("Deportes", 417), date(2026, 10, 15)), "DS-4170")

    def test_cambia_cada_mes(self):
        a = _aliado("Deportes", 417)
        codigos = {codigo_del_mes(a, date(2026, m, 1)) for m in range(1, 13)}
        self.assertEqual(len(codigos), 12)

    def test_ignora_tildes_espacios_y_mayusculas(self):
        self.assertEqual(codigo_del_mes(_aliado("  Mente Sana ", 100), date(2026, 3, 1)), "MA-0300")
        self.assertEqual(codigo_del_mes(_aliado("Ánimo", 100), date(2026, 3, 1)), "AO-0300")

    def test_trunca_a_cuatro_digitos(self):
        self.assertEqual(codigo_del_mes(_aliado("Soft", 999), date(2026, 12, 1)), "ST-1988")

    def test_codigo_fijo_gana(self):
        self.assertEqual(codigo_del_mes(_aliado("Soft", 999, "HGSOFT"), date(2026, 5, 1)), "HGSOFT")

    def test_nombre_sin_letras_falla(self):
        with self.assertRaises(ValueError):
            codigo_del_mes(_aliado("123", 100), date(2026, 5, 1))


class FechasTests(TestCase):
    def test_fin_de_mes(self):
        self.assertEqual(fin_de_mes(date(2026, 10, 3)), date(2026, 10, 31))
        self.assertEqual(fin_de_mes(date(2026, 2, 10)), date(2026, 2, 28))
        self.assertEqual(fin_de_mes(date(2026, 12, 31)), date(2026, 12, 31))

    def test_rango_mes_usa_hora_colombia(self):
        inicio, fin = _rango_mes_utc(date(2026, 10, 1))
        self.assertEqual(inicio, datetime(2026, 10, 1, tzinfo=TZ))
        self.assertEqual(fin, datetime(2026, 11, 1, tzinfo=TZ))
        self.assertEqual(inicio.utcoffset().total_seconds(), -5 * 3600)
