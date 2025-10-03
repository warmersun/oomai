CREATE TABLE public.license_mgmt (
  user_id     SERIAL PRIMARY KEY,
  username    VARCHAR(255) NOT NULL,
  client_reference_id VARCHAR(255) NOT NULL,
  paid_amount INTEGER DEFAULT 0 NOT NULL,
  CONSTRAINT unique_username UNIQUE (username),
  CONSTRAINT unique_client_reference_id UNIQUE (client_reference_id)
);
