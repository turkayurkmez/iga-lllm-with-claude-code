-- AOCC Copilot veri modeli (docs/spec.md §6). Alan adları sözleşmedir; değiştirmeyin.
-- İlk açılışta boş volume'a yüklenir (docker-entrypoint-initdb.d).

CREATE TABLE aircraft (
    registration  text PRIMARY KEY,
    type_icao     text NOT NULL,
    code_letter   char(1) NOT NULL CHECK (code_letter IN ('A', 'B', 'C', 'D', 'E', 'F')),
    operator_iata text NOT NULL
);

CREATE TABLE stands (
    stand_code      text PRIMARY KEY,
    stand_type      text NOT NULL CHECK (stand_type IN ('CONTACT', 'REMOTE')),
    max_code_letter char(1) NOT NULL CHECK (max_code_letter IN ('A', 'B', 'C', 'D', 'E', 'F')),
    mars            boolean NOT NULL,
    status          text NOT NULL CHECK (status IN ('AVAILABLE', 'UNAVAILABLE')),
    lat             double precision NOT NULL,
    lon             double precision NOT NULL
);

CREATE TABLE gates (
    gate_code  text PRIMARY KEY,
    terminal   text NOT NULL,
    pier       text NOT NULL,
    -- Boş: otobüs kapısı
    stand_code text REFERENCES stands (stand_code)
);

CREATE TABLE flights (
    flight_id      text PRIMARY KEY CHECK (flight_id ~ '^FL-[0-9]{8}-[0-9]{4}$'),
    flight_no      text NOT NULL,
    callsign       text NOT NULL,
    registration   text NOT NULL REFERENCES aircraft (registration),
    aircraft_type  text NOT NULL,
    origin         text NOT NULL,
    destination    text NOT NULL,
    scheduled_time timestamptz NOT NULL,
    estimated_time timestamptz NOT NULL,
    cancelled      boolean NOT NULL,
    -- Üreteç yazmaz; simülasyon saati ve yükleyici belirler.
    status         text NOT NULL DEFAULT 'SCHEDULED'
                   CHECK (status IN ('SCHEDULED', 'ACTIVE', 'COMPLETED', 'CANCELLED'))
);

CREATE INDEX flights_flight_no_idx ON flights (flight_no);
CREATE INDEX flights_callsign_idx ON flights (callsign);

CREATE TABLE movements (
    flight_id          text PRIMARY KEY REFERENCES flights (flight_id),
    movement_type      text NOT NULL CHECK (movement_type IN ('ARRIVAL', 'DEPARTURE')),
    stand_code         text REFERENCES stands (stand_code),
    gate_code          text REFERENCES gates (gate_code),
    actual_runway_time timestamptz,
    actual_block_time  timestamptz
);

CREATE TABLE positions (
    flight_id   text NOT NULL REFERENCES flights (flight_id),
    ts          timestamptz NOT NULL,
    lat         double precision NOT NULL,
    lon         double precision NOT NULL,
    heading_deg real NOT NULL,
    speed_kt    real NOT NULL,
    phase       text NOT NULL
                CHECK (phase IN ('APPROACH', 'TAXI_IN', 'AT_STAND', 'TAXI_OUT', 'CLIMB')),
    PRIMARY KEY (flight_id, ts)
);

CREATE TABLE delays (
    flight_id     text PRIMARY KEY REFERENCES flights (flight_id),
    delay_minutes integer NOT NULL CHECK (delay_minutes >= 15),
    -- İki haneli, IATA benzeri kurgusal kod
    delay_code    text NOT NULL CHECK (delay_code ~ '^[0-9]{2}$'),
    category      text NOT NULL CHECK (category IN (
                      'PASSENGER_BAGGAGE', 'AIRCRAFT_TECHNICAL', 'GROUND_HANDLING', 'WEATHER',
                      'ATC_RESTRICTION', 'AIRPORT_FACILITIES', 'REACTIONARY'))
);
