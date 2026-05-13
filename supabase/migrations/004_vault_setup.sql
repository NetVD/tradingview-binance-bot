-- =====================================================================
-- SkullTrading iOS — pgsodium / Vault setup for Binance credentials
-- Phase 1, Semaine 1
-- =====================================================================
-- Creates the dedicated pgsodium key used to encrypt Binance API
-- credentials, and a tiny SECURITY DEFINER helper that Edge Functions
-- call to decrypt a row in memory.
--
-- pgsodium is enabled by default on every Supabase project on the
-- "pgsodium" schema. The first time this migration runs it provisions
-- a key named 'binance_creds_v1'. Rotation later = create v2, copy data.
--
-- IMPORTANT
--   - This migration must be applied with a superuser role (the
--     Supabase migration runner does this automatically).
--   - Do NOT grant any decrypt function to anon or authenticated.
-- =====================================================================

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgsodium;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ---------------------------------------------------------------------
-- Provision the master encryption key (idempotent)
-- ---------------------------------------------------------------------
DO $$
DECLARE
    existing_key_id UUID;
BEGIN
    SELECT id INTO existing_key_id
    FROM pgsodium.key
    WHERE name = 'binance_creds_v1'
    LIMIT 1;

    IF existing_key_id IS NULL THEN
        PERFORM pgsodium.create_key(
            name        := 'binance_creds_v1',
            key_type    := 'aead-det'::pgsodium.key_type
        );
    END IF;
END
$$;

-- ---------------------------------------------------------------------
-- Helper: encrypt_binance_secret(plaintext, associated)
-- Called by the Edge Function 'binance-connect' (service_role).
-- Returns (ciphertext, nonce, key_id) so the row can be persisted.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.encrypt_binance_secret(
    plaintext TEXT,
    associated TEXT
)
RETURNS TABLE (
    ciphertext  BYTEA,
    nonce       BYTEA,
    key_id      UUID
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pgsodium
AS $$
DECLARE
    v_key_id UUID;
    v_nonce  BYTEA;
BEGIN
    SELECT id INTO v_key_id FROM pgsodium.key WHERE name = 'binance_creds_v1';
    IF v_key_id IS NULL THEN
        RAISE EXCEPTION 'pgsodium key binance_creds_v1 not provisioned';
    END IF;

    -- Deterministic AEAD uses a derived nonce — we still return a
    -- random nonce-shaped value for compatibility with future rotation
    -- to a non-deterministic scheme.
    v_nonce := gen_random_bytes(24);

    RETURN QUERY
    SELECT
        pgsodium.crypto_aead_det_encrypt(
            convert_to(plaintext, 'utf8'),
            convert_to(associated, 'utf8'),
            v_key_id
        ),
        v_nonce,
        v_key_id;
END;
$$;

REVOKE ALL ON FUNCTION public.encrypt_binance_secret(TEXT, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.encrypt_binance_secret(TEXT, TEXT) TO service_role;

-- ---------------------------------------------------------------------
-- Helper: decrypt_binance_secret(ciphertext, associated, key_id)
-- Called by the Edge Function 'binance-execute' (service_role).
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.decrypt_binance_secret(
    ciphertext BYTEA,
    associated TEXT,
    p_key_id   UUID
)
RETURNS TEXT
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pgsodium
AS $$
DECLARE
    v_plain BYTEA;
BEGIN
    v_plain := pgsodium.crypto_aead_det_decrypt(
        ciphertext,
        convert_to(associated, 'utf8'),
        p_key_id
    );
    RETURN convert_from(v_plain, 'utf8');
END;
$$;

REVOKE ALL ON FUNCTION public.decrypt_binance_secret(BYTEA, TEXT, UUID) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.decrypt_binance_secret(BYTEA, TEXT, UUID) TO service_role;

COMMIT;
