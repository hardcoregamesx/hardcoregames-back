-- Sistema de referidos. Idempotente (IF NOT EXISTS). Ejecutar contra la base `hardcoregames`.
-- La app `products` no usa migraciones: este archivo ES la definición del esquema.

CREATE TABLE IF NOT EXISTS referral_code (
    id          serial PRIMARY KEY,
    user_id     integer     NOT NULL UNIQUE REFERENCES auth_user(id) ON DELETE CASCADE,
    code        varchar(20) NOT NULL UNIQUE,   -- siempre en minúsculas, [a-z0-9]{4,20}
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS referral_reward (
    id               bigserial PRIMARY KEY,
    referrer_id      integer     NOT NULL REFERENCES auth_user(id),
    referred_user_id integer     NULL,
    code             varchar(20) NOT NULL,
    source_type      varchar(20) NOT NULL,     -- 'order' | 'preventa'
    source_ref       varchar(100) NOT NULL,    -- id de Transactions / transaction_id del Pago
    base_amount      integer     NOT NULL,     -- COP pagados por el cliente
    cashback         integer     NOT NULL,     -- COP acreditados (1%)
    status           varchar(12) NOT NULL DEFAULT 'credited',  -- credited | reverted
    created_at       timestamptz NOT NULL DEFAULT now(),
    reverted_at      timestamptz NULL,
    CONSTRAINT referral_reward_source_uq UNIQUE (source_type, source_ref)
);
CREATE INDEX IF NOT EXISTS referral_reward_referrer_idx ON referral_reward (referrer_id, created_at DESC);

-- Código de referido con el que se hizo la reserva de una preventa física.
ALTER TABLE preventas_reserva ADD COLUMN IF NOT EXISTS referral_code varchar(20) NOT NULL DEFAULT '';
