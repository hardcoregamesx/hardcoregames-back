from django.core.management.base import BaseCommand
from django.db import connection

SQL = """
CREATE TABLE IF NOT EXISTS preventas_preventa (
    id BIGSERIAL PRIMARY KEY,
    slug VARCHAR(80) NOT NULL UNIQUE,
    title VARCHAR(150) NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    image_url VARCHAR(500),
    reserva_unit INTEGER NOT NULL,
    breb_key VARCHAR(60) NOT NULL DEFAULT '',
    envio_nacional_est INTEGER NOT NULL DEFAULT 20000,
    pre_min INTEGER NOT NULL DEFAULT 0,
    pre_max INTEGER NOT NULL DEFAULT 0,
    pre_final INTEGER,
    switch_at TIMESTAMPTZ,
    tardia_min INTEGER NOT NULL DEFAULT 0,
    tardia_max INTEGER NOT NULL DEFAULT 0,
    tardia_final INTEGER,
    tardia_disponibles INTEGER,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS preventas_ciudad_intermedia (
    id BIGSERIAL PRIMARY KEY,
    nombre VARCHAR(80) NOT NULL UNIQUE,
    activa BOOLEAN NOT NULL DEFAULT TRUE,
    costo_estimado INTEGER,
    orden INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS preventas_reserva (
    id BIGSERIAL PRIMARY KEY,
    codigo VARCHAR(12) NOT NULL UNIQUE,
    preventa_id BIGINT NOT NULL REFERENCES preventas_preventa(id),
    fase VARCHAR(10) NOT NULL,
    unidades INTEGER NOT NULL,
    nombre VARCHAR(150) NOT NULL,
    whatsapp VARCHAR(30) NOT NULL,
    direccion VARCHAR(300) NOT NULL,
    ciudad VARCHAR(100) NOT NULL,
    cedula VARCHAR(20) NOT NULL,
    fuente VARCHAR(60) NOT NULL,
    envio_tipo VARCHAR(12) NOT NULL,
    ciudad_intermedia VARCHAR(80) NOT NULL DEFAULT '',
    reserva_total INTEGER NOT NULL,
    estado VARCHAR(12) NOT NULL DEFAULT 'PENDIENTE',
    guia VARCHAR(300) NOT NULL DEFAULT '',
    despachado_at TIMESTAMPTZ,
    notas TEXT NOT NULL DEFAULT '',
    expires_at TIMESTAMPTZ,
    paid_at TIMESTAMPTZ,
    saldo_paid_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS preventas_reserva_estado_idx ON preventas_reserva (estado);
CREATE INDEX IF NOT EXISTS preventas_reserva_preventa_idx ON preventas_reserva (preventa_id);
CREATE TABLE IF NOT EXISTS preventas_pago (
    id BIGSERIAL PRIMARY KEY,
    transaction_id VARCHAR(40) NOT NULL UNIQUE,
    reserva_id BIGINT NOT NULL REFERENCES preventas_reserva(id) ON DELETE CASCADE,
    tipo VARCHAR(8) NOT NULL,
    monto INTEGER NOT NULL,
    status VARCHAR(12) NOT NULL DEFAULT 'pendiente',
    nombre_pagador VARCHAR(150) NOT NULL DEFAULT '',
    breb_key VARCHAR(60) NOT NULL DEFAULT '',
    deadline_at VARCHAR(40) NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


class Command(BaseCommand):
    help = 'Crea (si no existen) las tablas del módulo Preventas. Idempotente; no usa migraciones.'

    def handle(self, *args, **options):
        with connection.cursor() as cur:
            cur.execute(SQL)
        self.stdout.write(self.style.SUCCESS('Tablas de preventas listas.'))
