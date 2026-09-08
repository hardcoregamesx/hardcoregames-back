-- Esquema para el modulo de beneficios de miembros pagos de YouTube.
--
-- Este proyecto no usa `manage.py migrate` en ningun app (ver nota en
-- membership/models.py y en products/models.py sobre ProductAlias):
-- las tablas se crean a mano, una sola vez, corriendo este archivo contra
-- la base real (psql, o `docker exec -i hc-postgres psql -U hardcoregames
-- -d hardcoregames < este_archivo.sql`). Los modelos Django/SQLAlchemy
-- correspondientes ya asumen que estas tablas existen (managed = False /
-- solo SELECT-INSERT-UPDATE, nunca create_all para estas).
--
-- NO CORRER contra produccion sin confirmar antes con el usuario. Probar
-- primero contra una copia/snapshot de hc-postgres.

BEGIN;

CREATE TABLE membership_youtubemembershiplink (
    id                    BIGSERIAL PRIMARY KEY,
    user_id               INTEGER NOT NULL UNIQUE REFERENCES auth_user(id),
    youtube_channel_id    VARCHAR(64) NOT NULL UNIQUE,
    youtube_display_name  VARCHAR(255) NOT NULL DEFAULT '',
    tier                  VARCHAR(10) CHECK (tier IN ('LOW', 'MID', 'HIGH')),
    status                VARCHAR(10) NOT NULL DEFAULT 'INACTIVE' CHECK (status IN ('ACTIVE', 'INACTIVE')),
    linked_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_synced_at        TIMESTAMPTZ
);

CREATE TABLE membership_levelmapping (
    id                 BIGSERIAL PRIMARY KEY,
    google_level_name  VARCHAR(255) NOT NULL UNIQUE,
    tier               VARCHAR(10) NOT NULL CHECK (tier IN ('LOW', 'MID', 'HIGH'))
);

CREATE TABLE membership_pointsclaim (
    id               BIGSERIAL PRIMARY KEY,
    user_id          INTEGER NOT NULL REFERENCES auth_user(id),
    week_start_date  DATE NOT NULL,
    points_awarded   INTEGER NOT NULL,
    claimed_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, week_start_date)
);

CREATE TABLE membership_discountlog (
    id               BIGSERIAL PRIMARY KEY,
    transaction_id   INTEGER NOT NULL REFERENCES products_transactions(id_transaction),
    user_id          INTEGER NOT NULL REFERENCES auth_user(id),
    tier             VARCHAR(10) NOT NULL,
    percent_applied  NUMERIC(5, 2) NOT NULL,
    amount_saved     INTEGER NOT NULL,
    applied_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE membership_googleoauthcredential (
    id                       BIGSERIAL PRIMARY KEY,
    provider                 VARCHAR(30) NOT NULL UNIQUE,
    refresh_token             TEXT NOT NULL,
    access_token_cache        TEXT NOT NULL DEFAULT '',
    access_token_expires_at   TIMESTAMPTZ,
    updated_at                TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Reusar la ruleta existente para la ruleta VIP en vez de duplicar tablas:
-- una segunda fila en rewards_roulette con requires_membership = true y
-- max_spins_per_month en vez de max_spins_per_day.
ALTER TABLE rewards_roulette ADD COLUMN requires_membership BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE rewards_roulette ADD COLUMN max_spins_per_month INTEGER;

-- Nuevo motivo de PointTransaction para el reclamo semanal VIP. El nombre
-- del constraint se confirmo leyendo el modelo SQLAlchemy
-- (app/models.py:326-330 en el repo fastapi) — no se adivino.
ALTER TABLE rewards_pointtransaction DROP CONSTRAINT rewards_pointtransaction_reason_check;
ALTER TABLE rewards_pointtransaction ADD CONSTRAINT rewards_pointtransaction_reason_check
    CHECK (reason IN ('PURCHASE', 'ROULETTE_SPIN', 'COUPON', 'EXCHANGE', 'ADMIN_ADJUST', 'REFUND', 'YOUTUBE_MEMBER_CLAIM'));

COMMIT;
