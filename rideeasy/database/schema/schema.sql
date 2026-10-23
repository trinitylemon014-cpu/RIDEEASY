-- RideEasy Production Database Schema (libSQL / Turso & SQLite Compatible)
-- Brand: RideEasy | Emtrixz Technology Company | MOVE. TRAVEL. ARRIVE.

PRAGMA foreign_keys = ON;

-- Core Users Table with Role-Based Access Control
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('PASSENGER', 'DRIVER', 'SCHOOL', 'TRAVEL_COMPANY', 'ADMIN')),
    full_name TEXT NOT NULL,
    phone TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    is_verified INTEGER NOT NULL DEFAULT 0,
    avatar_url TEXT DEFAULT '/static/images/default-avatar.svg',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Passenger Profiles
CREATE TABLE IF NOT EXISTS passenger_profiles (
    user_id TEXT PRIMARY KEY,
    emergency_contact_name TEXT,
    emergency_contact_phone TEXT,
    preferred_payment_method TEXT DEFAULT 'MTN_MOMO',
    home_address TEXT,
    work_address TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- Driver Profiles
CREATE TABLE IF NOT EXISTS driver_profiles (
    user_id TEXT PRIMARY KEY,
    license_number TEXT NOT NULL,
    national_id_nin TEXT NOT NULL,
    years_experience INTEGER DEFAULT 1,
    verification_status TEXT NOT NULL DEFAULT 'PENDING' CHECK(verification_status IN ('PENDING', 'APPROVED', 'REJECTED')),
    is_online INTEGER NOT NULL DEFAULT 0,
    current_lat REAL,
    current_lng REAL,
    rating_avg REAL DEFAULT 5.0,
    rating_count INTEGER DEFAULT 0,
    total_trips INTEGER DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- Vehicles
CREATE TABLE IF NOT EXISTS vehicles (
    id TEXT PRIMARY KEY,
    driver_id TEXT,
    make TEXT NOT NULL,
    model TEXT NOT NULL,
    year INTEGER NOT NULL,
    color TEXT NOT NULL,
    plate_number TEXT UNIQUE NOT NULL,
    category TEXT NOT NULL CHECK(category IN ('BODA', 'ECONOMY', 'COMFORT', 'PREMIUM', 'COASTER', 'BUS')),
    capacity INTEGER NOT NULL DEFAULT 4,
    is_active INTEGER NOT NULL DEFAULT 1,
    is_verified INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (driver_id) REFERENCES users(id) ON DELETE SET NULL
);

-- Driver Verification Documents
CREATE TABLE IF NOT EXISTS driver_documents (
    id TEXT PRIMARY KEY,
    driver_id TEXT NOT NULL,
    doc_type TEXT NOT NULL CHECK(doc_type IN ('DRIVING_PERMIT', 'NATIONAL_ID', 'POLICE_CLEARANCE', 'VEHICLE_LOGBOOK')),
    doc_number TEXT,
    status TEXT NOT NULL DEFAULT 'APPROVED' CHECK(status IN ('PENDING', 'APPROVED', 'REJECTED')),
    submitted_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (driver_id) REFERENCES users(id) ON DELETE CASCADE
);

-- Schools
CREATE TABLE IF NOT EXISTS schools (
    user_id TEXT PRIMARY KEY,
    school_name TEXT NOT NULL,
    registration_number TEXT NOT NULL,
    contact_person TEXT NOT NULL,
    phone TEXT NOT NULL,
    email TEXT NOT NULL,
    address TEXT NOT NULL,
    district TEXT NOT NULL DEFAULT 'Kampala',
    student_count INTEGER DEFAULT 500,
    verification_status TEXT NOT NULL DEFAULT 'APPROVED' CHECK(verification_status IN ('PENDING', 'APPROVED', 'REJECTED')),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- School Transport Requests (Buses and Coasters)
CREATE TABLE IF NOT EXISTS school_transport_requests (
    id TEXT PRIMARY KEY,
    school_id TEXT NOT NULL,
    vehicle_type TEXT NOT NULL CHECK(vehicle_type IN ('COASTER', 'BUS')),
    passenger_count INTEGER NOT NULL,
    pickup_location TEXT NOT NULL,
    destination TEXT NOT NULL,
    travel_date TEXT NOT NULL,
    departure_time TEXT NOT NULL,
    return_date TEXT,
    return_time TEXT,
    special_requirements TEXT,
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING', 'APPROVED', 'VEHICLE_ASSIGNED', 'IN_TRANSIT', 'COMPLETED', 'CANCELLED')),
    assigned_driver_id TEXT,
    assigned_vehicle_id TEXT,
    agreed_price_ugx INTEGER,
    invoice_status TEXT NOT NULL DEFAULT 'PENDING' CHECK(invoice_status IN ('PENDING', 'INVOICED', 'PAID')),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (school_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (assigned_driver_id) REFERENCES users(id),
    FOREIGN KEY (assigned_vehicle_id) REFERENCES vehicles(id)
);

-- Verified Travel Companies
CREATE TABLE IF NOT EXISTS travel_companies (
    user_id TEXT PRIMARY KEY,
    company_name TEXT NOT NULL,
    license_number TEXT NOT NULL,
    contact_person TEXT NOT NULL,
    phone TEXT NOT NULL,
    email TEXT NOT NULL,
    physical_address TEXT NOT NULL,
    verification_status TEXT NOT NULL DEFAULT 'APPROVED' CHECK(verification_status IN ('PENDING', 'APPROVED', 'REJECTED')),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- Flight Assistance Requests
CREATE TABLE IF NOT EXISTS flight_requests (
    id TEXT PRIMARY KEY,
    passenger_id TEXT NOT NULL,
    departure_city TEXT NOT NULL,
    destination_city TEXT NOT NULL,
    departure_date TEXT NOT NULL,
    return_date TEXT,
    passenger_count INTEGER NOT NULL DEFAULT 1,
    preferred_airline TEXT,
    cabin_class TEXT DEFAULT 'Economy',
    phone TEXT NOT NULL,
    email TEXT NOT NULL,
    travel_preferences TEXT,
    notes TEXT,
    assigned_company_id TEXT,
    status TEXT NOT NULL DEFAULT 'SUBMITTED' CHECK(status IN ('SUBMITTED', 'ASSIGNED', 'QUOTED', 'CUSTOMER_APPROVED', 'CONFIRMED', 'DECLINED', 'CANCELLED')),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (passenger_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (assigned_company_id) REFERENCES users(id)
);

-- Flight Quotations from Travel Companies
CREATE TABLE IF NOT EXISTS flight_quotations (
    id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    travel_company_id TEXT NOT NULL,
    quote_reference TEXT UNIQUE NOT NULL,
    proposed_airline TEXT NOT NULL,
    flight_number TEXT NOT NULL,
    departure_time TEXT NOT NULL,
    arrival_time TEXT NOT NULL,
    itinerary_summary TEXT NOT NULL,
    price_ugx INTEGER NOT NULL,
    valid_until TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING', 'ACCEPTED', 'DECLINED')),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (request_id) REFERENCES flight_requests(id) ON DELETE CASCADE,
    FOREIGN KEY (travel_company_id) REFERENCES users(id)
);

-- Confirmed Flight Bookings (Recorded by Travel Companies)
CREATE TABLE IF NOT EXISTS flight_bookings (
    id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    travel_company_id TEXT NOT NULL,
    booking_reference_pnr TEXT NOT NULL,
    airline_ticket_number TEXT,
    airline_name TEXT NOT NULL,
    flight_number TEXT NOT NULL,
    departure_airport TEXT NOT NULL,
    arrival_airport TEXT NOT NULL,
    departure_datetime TEXT NOT NULL,
    arrival_datetime TEXT,
    status TEXT NOT NULL DEFAULT 'CONFIRMED' CHECK(status IN ('CONFIRMED', 'RESCHEDULED', 'CANCELLED')),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (request_id) REFERENCES flight_requests(id) ON DELETE CASCADE,
    FOREIGN KEY (travel_company_id) REFERENCES users(id)
);

-- Confirmed Journeys (For travel itinerary and reminders)
CREATE TABLE IF NOT EXISTS confirmed_journeys (
    id TEXT PRIMARY KEY,
    passenger_id TEXT NOT NULL,
    flight_booking_id TEXT NOT NULL,
    journey_type TEXT NOT NULL DEFAULT 'OUTBOUND_FLIGHT',
    departure_datetime TEXT NOT NULL,
    origin TEXT NOT NULL,
    destination TEXT NOT NULL,
    airport_ride_booked INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'SCHEDULED' CHECK(status IN ('SCHEDULED', 'ACTIVE', 'COMPLETED', 'CANCELLED')),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (passenger_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (flight_booking_id) REFERENCES flight_bookings(id) ON DELETE CASCADE
);

-- Journey Reminders (7d, 3d, 2d, 1d, Travel Day)
CREATE TABLE IF NOT EXISTS journey_reminders (
    id TEXT PRIMARY KEY,
    journey_id TEXT NOT NULL,
    reminder_type TEXT NOT NULL CHECK(reminder_type IN ('7_DAYS', '3_DAYS', '2_DAYS', '1_DAY', 'TRAVEL_DAY')),
    scheduled_for TEXT NOT NULL,
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    is_delivered INTEGER NOT NULL DEFAULT 0,
    delivered_at TEXT,
    channel TEXT NOT NULL DEFAULT 'IN_APP',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (journey_id) REFERENCES confirmed_journeys(id) ON DELETE CASCADE
);

-- Ride-Hailing Trips
CREATE TABLE IF NOT EXISTS rides (
    id TEXT PRIMARY KEY,
    passenger_id TEXT NOT NULL,
    driver_id TEXT,
    category TEXT NOT NULL CHECK(category IN ('BODA', 'ECONOMY', 'COMFORT', 'PREMIUM')),
    pickup_address TEXT NOT NULL,
    pickup_lat REAL NOT NULL,
    pickup_lng REAL NOT NULL,
    destination_address TEXT NOT NULL,
    destination_lat REAL NOT NULL,
    destination_lng REAL NOT NULL,
    estimated_distance_km REAL NOT NULL,
    estimated_fare_ugx INTEGER NOT NULL,
    final_fare_ugx INTEGER,
    payment_method TEXT NOT NULL DEFAULT 'CASH' CHECK(payment_method IN ('CASH', 'MTN_MOMO', 'AIRTEL_MONEY', 'CARD')),
    payment_status TEXT NOT NULL DEFAULT 'UNPAID' CHECK(payment_status IN ('UNPAID', 'PENDING', 'PAID')),
    status TEXT NOT NULL DEFAULT 'REQUESTED' CHECK(status IN (
        'REQUESTED',
        'SEARCHING_FOR_DRIVER',
        'DRIVER_ASSIGNED',
        'DRIVER_ARRIVING',
        'DRIVER_ARRIVED',
        'TRIP_STARTED',
        'TRIP_COMPLETED',
        'PAYMENT_PENDING',
        'COMPLETED',
        'CANCELLED'
    )),
    cancellation_reason TEXT,
    cancelled_at TIMESTAMP,
    is_airport_ride INTEGER NOT NULL DEFAULT 0,
    related_journey_id TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (passenger_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (driver_id) REFERENCES users(id),
    FOREIGN KEY (related_journey_id) REFERENCES confirmed_journeys(id)
);

-- Paystack charges are pending until a signed callback or return URL is verified server-side.
CREATE TABLE IF NOT EXISTS payment_transactions (
    id TEXT PRIMARY KEY,
    ride_id TEXT NOT NULL,
    passenger_id TEXT NOT NULL,
    reference TEXT NOT NULL UNIQUE,
    provider_reference TEXT,
    authorization_url TEXT,
    amount_ugx INTEGER NOT NULL CHECK(amount_ugx > 0),
    currency TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING', 'PAID', 'FAILED')),
    payer_name TEXT,
    paid_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (ride_id) REFERENCES rides(id),
    FOREIGN KEY (passenger_id) REFERENCES users(id)
);

-- Immutable earned shares; payout_status tracks the later manual mobile-money payout.
CREATE TABLE IF NOT EXISTS payment_ledger (
    id TEXT PRIMARY KEY,
    payment_id TEXT NOT NULL,
    recipient_id TEXT NOT NULL,
    recipient_role TEXT NOT NULL CHECK(recipient_role IN ('ADMIN', 'DRIVER')),
    recipient_name TEXT NOT NULL,
    recipient_phone TEXT NOT NULL,
    amount_ugx INTEGER NOT NULL CHECK(amount_ugx >= 0),
    payout_status TEXT NOT NULL DEFAULT 'PENDING' CHECK(payout_status IN ('PENDING', 'PAID')),
    paid_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(payment_id, recipient_role),
    FOREIGN KEY (payment_id) REFERENCES payment_transactions(id),
    FOREIGN KEY (recipient_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS payment_settings (
    setting_key TEXT PRIMARY KEY,
    setting_value TEXT NOT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Points are awarded once for each completed ride with a verified payment.
CREATE TABLE IF NOT EXISTS reward_point_awards (
    ride_id TEXT PRIMARY KEY,
    passenger_id TEXT NOT NULL,
    points INTEGER NOT NULL CHECK(points > 0),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (ride_id) REFERENCES rides(id),
    FOREIGN KEY (passenger_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS sms_messages (
    id TEXT PRIMARY KEY,
    payment_id TEXT NOT NULL,
    recipient_phone TEXT NOT NULL,
    message TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('SENT', 'FAILED', 'NOT_CONFIGURED')),
    provider_message_id TEXT,
    error_message TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (payment_id) REFERENCES payment_transactions(id)
);

-- In-App Notifications
CREATE TABLE IF NOT EXISTS notifications (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'SYSTEM' CHECK(type IN ('DRIVER_ASSIGNED', 'RIDE_STATUS', 'CANCELLATION', 'REMINDER', 'SYSTEM')),
    is_read INTEGER NOT NULL DEFAULT 0,
    related_entity_id TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- Ride Ratings and Reviews
CREATE TABLE IF NOT EXISTS ride_ratings (
    id TEXT PRIMARY KEY,
    ride_id TEXT UNIQUE NOT NULL,
    passenger_id TEXT NOT NULL,
    driver_id TEXT NOT NULL,
    rating INTEGER NOT NULL CHECK(rating >= 1 AND rating <= 5),
    review TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (ride_id) REFERENCES rides(id) ON DELETE CASCADE,
    FOREIGN KEY (passenger_id) REFERENCES users(id),
    FOREIGN KEY (driver_id) REFERENCES users(id)
);

-- Pricing Configurations (Base, Per Km, Minimum Fare in UGX)
CREATE TABLE IF NOT EXISTS pricing_configs (
    category TEXT PRIMARY KEY,
    base_fare_ugx INTEGER NOT NULL,
    per_km_ugx INTEGER NOT NULL,
    per_min_ugx INTEGER NOT NULL,
    min_fare_ugx INTEGER NOT NULL
);

-- Security and Operational Audit Logs
CREATE TABLE IF NOT EXISTS audit_logs (
    id TEXT PRIMARY KEY,
    user_id TEXT,
    action TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id TEXT,
    details TEXT,
    ip_address TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
);

-- Saved Routes for Frequent Passenger Travel (e.g. 'Home to Office')
CREATE TABLE IF NOT EXISTS saved_routes (
    id TEXT PRIMARY KEY,
    passenger_id TEXT NOT NULL,
    name TEXT NOT NULL,
    pickup_address TEXT NOT NULL,
    destination_address TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'ECONOMY',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (passenger_id) REFERENCES users(id) ON DELETE CASCADE
);

-- Passenger Rewards Redemptions
CREATE TABLE IF NOT EXISTS rewards_redemptions (
    id TEXT PRIMARY KEY,
    passenger_id TEXT NOT NULL,
    reward_id TEXT NOT NULL,
    reward_title TEXT NOT NULL,
    points_spent INTEGER NOT NULL,
    voucher_code TEXT UNIQUE NOT NULL,
    discount_ugx INTEGER DEFAULT 0,
    discount_percent INTEGER NOT NULL DEFAULT 0 CHECK(discount_percent BETWEEN 0 AND 100),
    ride_id TEXT,
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE', 'USED', 'EXPIRED')),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP,
    FOREIGN KEY (passenger_id) REFERENCES users(id) ON DELETE CASCADE
);

-- Performance Indexes
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);
CREATE INDEX IF NOT EXISTS idx_rides_passenger ON rides(passenger_id);
CREATE INDEX IF NOT EXISTS idx_rides_driver ON rides(driver_id);
CREATE INDEX IF NOT EXISTS idx_rides_status ON rides(status);
CREATE INDEX IF NOT EXISTS idx_flight_requests_passenger ON flight_requests(passenger_id);
CREATE INDEX IF NOT EXISTS idx_flight_requests_company ON flight_requests(assigned_company_id);
CREATE INDEX IF NOT EXISTS idx_school_requests_school ON school_transport_requests(school_id);
CREATE INDEX IF NOT EXISTS idx_reminders_journey ON journey_reminders(journey_id);
CREATE INDEX IF NOT EXISTS idx_saved_routes_passenger ON saved_routes(passenger_id);
CREATE INDEX IF NOT EXISTS idx_rewards_redemptions_passenger ON rewards_redemptions(passenger_id);
CREATE INDEX IF NOT EXISTS idx_payment_transactions_ride ON payment_transactions(ride_id);
CREATE INDEX IF NOT EXISTS idx_payment_transactions_status ON payment_transactions(status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_payment_one_active_per_ride
    ON payment_transactions(ride_id) WHERE status IN ('PENDING', 'PAID');
CREATE INDEX IF NOT EXISTS idx_payment_ledger_recipient ON payment_ledger(recipient_id, created_at);
CREATE INDEX IF NOT EXISTS idx_payment_ledger_status ON payment_ledger(payout_status, created_at);
CREATE INDEX IF NOT EXISTS idx_reward_point_awards_passenger ON reward_point_awards(passenger_id);
