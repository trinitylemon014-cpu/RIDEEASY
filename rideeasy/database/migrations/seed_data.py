import uuid
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash
from flask import current_app, has_app_context
from app.repositories.database import get_db
from app.config import Config

def _schema_fingerprint():
    """Hash of every file that defines the schema or its migrations.

    Editing schema.sql, seed_data.py or database.py changes it, which makes the next
    start re-run the (idempotent) one-time setup once and then record the new value.
    """
    import hashlib
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(os.path.dirname(here))
    digest = hashlib.sha256()
    for path in (
        os.path.join(root, "database", "schema", "schema.sql"),
        os.path.abspath(__file__),
        os.path.join(root, "app", "repositories", "database.py"),
    ):
        try:
            with open(path, "rb") as handle:
                digest.update(handle.read())
        except OSError:
            digest.update(b"missing:" + path.encode())
    return digest.hexdigest()[:16]


def _one_time_setup(db, collection_phone, admin_payout_phone):
    """Idempotent static setup (payment settings, column migrations, tables, pricing)."""
    for setting_key, setting_value in (
        ("collection_phone", collection_phone),
        ("admin_payout_phone", admin_payout_phone),
        ("admin_payout_name", "RideEasy Admin")
    ):
        db.execute(
            "INSERT OR IGNORE INTO payment_settings (setting_key, setting_value) VALUES (?, ?)",
            (setting_key, setting_value)
        )

    # Migration for new columns if existing database
    try:
        db.execute("ALTER TABLE users ADD COLUMN avatar_url TEXT DEFAULT '/static/images/default-avatar.svg'")
    except Exception:
        pass

    try:
        db.execute("ALTER TABLE rides ADD COLUMN cancelled_at TIMESTAMP")
    except Exception:
        pass

    db.execute("""CREATE TABLE IF NOT EXISTS notifications (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        title TEXT NOT NULL,
        message TEXT NOT NULL,
        type TEXT NOT NULL DEFAULT 'SYSTEM',
        is_read INTEGER NOT NULL DEFAULT 0,
        related_entity_id TEXT,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""")

    db.execute("""CREATE TABLE IF NOT EXISTS saved_routes (
        id TEXT PRIMARY KEY,
        passenger_id TEXT NOT NULL,
        name TEXT NOT NULL,
        pickup_address TEXT NOT NULL,
        destination_address TEXT NOT NULL,
        category TEXT NOT NULL DEFAULT 'ECONOMY',
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (passenger_id) REFERENCES users(id) ON DELETE CASCADE
    )""")

    db.execute("""CREATE TABLE IF NOT EXISTS rewards_redemptions (
        id TEXT PRIMARY KEY,
        passenger_id TEXT NOT NULL,
        reward_id TEXT NOT NULL,
        reward_title TEXT NOT NULL,
        points_spent INTEGER NOT NULL,
        voucher_code TEXT UNIQUE NOT NULL,
        discount_ugx INTEGER DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE', 'USED', 'EXPIRED')),
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        expires_at TIMESTAMP,
        FOREIGN KEY (passenger_id) REFERENCES users(id) ON DELETE CASCADE
    )""")

    # Pricing Configurations (Ugandan Shillings - UGX)
    pricing = [
        ("BODA", 1500, 700, 100, 2500),
        ("ECONOMY", 3500, 1500, 200, 6000),
        ("COMFORT", 5000, 2200, 300, 9000),
        ("PREMIUM", 8000, 3200, 450, 15000),
        ("COASTER", 80000, 4500, 500, 250000),
        ("BUS", 150000, 7500, 800, 450000)
    ]
    for cat, base, per_km, per_min, min_f in pricing:
        db.execute(
            "INSERT OR IGNORE INTO pricing_configs (category, base_fare_ugx, per_km_ugx, per_min_ugx, min_fare_ugx) VALUES (?, ?, ?, ?, ?)",
            (cat, base, per_km, per_min, min_f)
        )


def seed_database(include_demo_data=None):
    """Initialize shared pricing and provision accounts or test fixtures."""
    db = get_db()
    # The schema, column migrations and static rows only need to run when something
    # changed. Skipping them saves ~70 network round trips on every start/wake-up.
    fingerprint = _schema_fingerprint()
    setup_needed = not db.schema_is_current(fingerprint)
    if setup_needed:
        db.init_db()
    if include_demo_data is None:
        include_demo_data = has_app_context() and current_app.testing
    if has_app_context():
        collection_phone = current_app.config["PAYSTACK_COLLECTION_PHONE"]
        admin_payout_phone = current_app.config["PAYSTACK_ADMIN_PAYOUT_PHONE"]
        admin_email = current_app.config["ADMIN_EMAIL"]
        admin_name = current_app.config["ADMIN_NAME"]
        admin_password = current_app.config["ADMIN_PASSWORD"]
        admin_phone = current_app.config["ADMIN_PHONE"]
    else:
        collection_phone = Config.PAYSTACK_COLLECTION_PHONE
        admin_payout_phone = Config.PAYSTACK_ADMIN_PAYOUT_PHONE
        admin_email = Config.ADMIN_EMAIL
        admin_name = Config.ADMIN_NAME
        admin_password = Config.ADMIN_PASSWORD
        admin_phone = Config.ADMIN_PHONE
    if setup_needed:
        _one_time_setup(db, collection_phone, admin_payout_phone)
        db.mark_schema_current(fingerprint)

    if not include_demo_data:
        if not admin_password:
            raise RuntimeError("ADMIN_PASSWORD must be set to provision the production administrator.")
        _remove_legacy_demo_data(db)
        admin = db.fetchone("SELECT id, role FROM users WHERE email = ?", (admin_email,))
        if admin and admin["role"] != "ADMIN":
            raise RuntimeError(f"Cannot provision administrator: {admin_email} is already assigned to another role.")
        if not admin:
            db.execute(
                """INSERT INTO users
                   (id, email, password_hash, role, full_name, phone, is_active, is_verified)
                   VALUES (?, ?, ?, 'ADMIN', ?, ?, 1, 1)""",
                (f"usr_{uuid.uuid4().hex[:10]}", admin_email, generate_password_hash(admin_password), admin_name, admin_phone)
            )
        else:
            db.execute(
                "UPDATE users SET full_name = ?, is_active = 1, is_verified = 1 WHERE id = ?",
                (admin_name, admin["id"])
            )
        return

    # Demo accounts and fixtures are only created by the test suite.
    if not admin_password:
        raise RuntimeError("ADMIN_PASSWORD must be set when seeding test accounts.")
    default_pw = generate_password_hash(uuid.uuid4().hex)
    admin_pw = generate_password_hash(admin_password)

    users = [
        # (id, email, pw, role, full_name, phone, is_verified)
        ("usr_admin_01", admin_email, admin_pw, "ADMIN", admin_name, admin_phone, 1),
        ("usr_pass_01", "passenger@rideeasy.ug", default_pw, "PASSENGER", "Grace Namubiru", "+256 772 123 456", 1),
        ("usr_driver_01", "driver@rideeasy.ug", default_pw, "DRIVER", "David Okello", "+256 754 445 566", 1),
        ("usr_school_01", "school@rideeasy.ug", default_pw, "SCHOOL", "Greenhill Academy Kampala", "+256 414 342 900", 1),
        ("usr_travel_01", "travel@rideeasy.ug", default_pw, "TRAVEL_COMPANY", "Nile Equatorial Travel Agency", "+256 312 880 770", 1),
    ]

    for uid, email, pw, role, name, phone, verified in users:
        db.execute(
            "INSERT OR IGNORE INTO users (id, email, password_hash, role, full_name, phone, is_active, is_verified) VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
            (uid, email, pw, role, name, phone, verified)
        )

    existing_admin = db.fetchone("SELECT id FROM users WHERE email = ?", (admin_email,))
    if existing_admin:
        notif = db.fetchone("SELECT id FROM notifications WHERE id = ?", ("notif_demo_01",))
        if not notif:
            db.execute(
                "INSERT INTO notifications (id, user_id, title, message, type, is_read, related_entity_id) VALUES (?, ?, ?, ?, ?, 0, ?)",
                ("notif_demo_01", "usr_pass_01", "Driver Assigned", "David Okello (Toyota Premio UBD 204K) has been assigned to your trip #RIDE_01.", "DRIVER_ASSIGNED", "ride_01")
            )
        redemption = db.fetchone("SELECT id FROM rewards_redemptions WHERE id = ?", ("red_demo_01",))
        if not redemption:
            db.execute(
                """INSERT INTO rewards_redemptions
                (id, passenger_id, reward_id, reward_title, points_spent, voucher_code, discount_ugx, status, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'ACTIVE', datetime('now', '-2 days'), datetime('now', '+58 days'))""",
                ("red_demo_01", "usr_pass_01", "rew_toll_pass", "Entebbe Expressway Toll Pass", 200, "REWARD-TOLL-9421", 5000)
            )

    # 3. Passenger Profile
    db.execute(
        "INSERT OR IGNORE INTO passenger_profiles (user_id, emergency_contact_name, emergency_contact_phone, preferred_payment_method, home_address, work_address) VALUES (?, ?, ?, ?, ?, ?)",
        ("usr_pass_01", "Moses Namubiru", "+256 772 999 000", "MTN_MOMO", "Plot 14 Acacia Avenue, Kololo, Kampala", "Victoria Towers, Nakasero Road, Kampala")
    )

    # 4. Driver Profile & Vehicle
    db.execute(
        "INSERT OR IGNORE INTO driver_profiles (user_id, license_number, national_id_nin, years_experience, verification_status, is_online, current_lat, current_lng, rating_avg, rating_count, total_trips) VALUES (?, ?, ?, ?, 'APPROVED', 1, 0.3200, 32.5850, 4.9, 142, 384)",
        ("usr_driver_01", "DL-UGA-2023-88910", "CM89024104KPL", 6)
    )

    db.execute(
        "INSERT OR IGNORE INTO vehicles (id, driver_id, make, model, year, color, plate_number, category, capacity, is_active, is_verified) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1)",
        ("veh_01", "usr_driver_01", "Toyota", "Premio", 2018, "Silver", "UBD 204K", "ECONOMY", 4)
    )

    # 5. School Profile
    db.execute(
        "INSERT OR IGNORE INTO schools (user_id, school_name, registration_number, contact_person, phone, email, address, district, student_count, verification_status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'APPROVED')",
        ("usr_school_01", "Greenhill Academy Kibuli", "MOES/KLA/SCH/1029", "Sister Evelyn Mwebaza", "+256 414 342 900", "school@rideeasy.ug", "Kibuli Hill Road, Makindye Division, Kampala", "Kampala", 1200)
    )

    # Sample School Transport Request
    db.execute(
        """INSERT OR IGNORE INTO school_transport_requests 
        (id, school_id, vehicle_type, passenger_count, pickup_location, destination, travel_date, departure_time, return_date, return_time, special_requirements, status, agreed_price_ugx, invoice_status) 
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'APPROVED', ?, 'INVOICED')""",
        ("req_sch_01", "usr_school_01", "COASTER", 28, "Greenhill Academy Kibuli Campus", "Entebbe Uganda Wildlife Education Centre (UWEC)", "2026-11-12", "08:00 AM", "2026-11-12", "04:30 PM", "Air conditioning required. 2 first aid kits on board. Primary 5 Science Study Tour.", 380000)
    )

    # 6. Travel Company Profile
    db.execute(
        "INSERT OR IGNORE INTO travel_companies (user_id, company_name, license_number, contact_person, phone, email, physical_address, verification_status) VALUES (?, ?, ?, ?, ?, ?, ?, 'APPROVED')",
        ("usr_travel_01", "Nile Equatorial Travel Agency Ltd", "TUG-LIC-77821-2026", "Brenda Nalubega", "+256 312 880 770", "travel@rideeasy.ug", "Workers House, 3rd Floor, Pilkington Road, Kampala")
    )

    # Sample Flight Request, Quotation & Booking
    db.execute(
        """INSERT OR IGNORE INTO flight_requests 
        (id, passenger_id, departure_city, destination_city, departure_date, return_date, passenger_count, preferred_airline, cabin_class, phone, email, travel_preferences, notes, assigned_company_id, status) 
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'CONFIRMED')""",
        ("flt_req_01", "usr_pass_01", "Entebbe (EBB)", "Dubai (DXB)", "2026-11-15", "2026-11-22", 1, "Emirates / Uganda Airlines", "Economy", "+256 772 123 456", "passenger@rideeasy.ug", "Aisle seat requested", "International Trade & Investment Conference", "usr_travel_01")
    )

    db.execute(
        """INSERT OR IGNORE INTO flight_quotations 
        (id, request_id, travel_company_id, quote_reference, proposed_airline, flight_number, departure_time, arrival_time, itinerary_summary, price_ugx, valid_until, status) 
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ACCEPTED')""",
        ("quote_01", "flt_req_01", "usr_travel_01", "QUO-DXB-9842", "Uganda Airlines", "UR 446", "17:30 EAT", "23:45 GST", "Entebbe Direct to Dubai International Terminal 1. Baggage 2x 23kg included.", 2450000, "2026-11-05")
    )

    db.execute(
        """INSERT OR IGNORE INTO flight_bookings 
        (id, request_id, travel_company_id, booking_reference_pnr, airline_ticket_number, airline_name, flight_number, departure_airport, arrival_airport, departure_datetime, arrival_datetime, status) 
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'CONFIRMED')""",
        ("bk_01", "flt_req_01", "usr_travel_01", "6R9KQ2", "673-2491028472", "Uganda Airlines", "UR 446", "Entebbe International Airport (EBB)", "Dubai International Airport (DXB)", "2026-11-15 17:30:00", "2026-11-15 23:45:00")
    )

    # Confirmed Journey for Travel Reminders & Airport Ride
    db.execute(
        """INSERT OR IGNORE INTO confirmed_journeys 
        (id, passenger_id, flight_booking_id, journey_type, departure_datetime, origin, destination, airport_ride_booked, status) 
        VALUES (?, ?, ?, 'OUTBOUND_FLIGHT', ?, ?, ?, 0, 'SCHEDULED')""",
        ("jrn_01", "usr_pass_01", "bk_01", "2026-11-15 17:30:00", "Kampala / Entebbe EBB", "Dubai DXB")
    )

    # Automated 5-stage travel reminders
    reminders = [
        ("rem_01", "jrn_01", "7_DAYS", "2026-11-08 09:00:00", "Passport & Visa Verification", "7 days until your flight to Dubai (UR 446). Verify your passport validity has at least 6 months remaining and your UAE entry visa is approved.", 1),
        ("rem_02", "jrn_01", "3_DAYS", "2026-11-12 09:00:00", "Airport Transport Arrangement", "3 days until departure. Book your RideEasy airport ride from Kampala to Entebbe Airport (EBB) to avoid expressway delays.", 0),
        ("rem_03", "jrn_01", "2_DAYS", "2026-11-13 09:00:00", "Luggage & Packing Checklist", "2 days to go. Check baggage allowance (2x 23kg for Uganda Airlines) and prepare liquids in containers under 100ml.", 0),
        ("rem_04", "jrn_01", "1_DAY", "2026-11-14 09:00:00", "Online Check-in Open", "24 hours to departure. Online check-in is now open. Confirm your seat selection and download your boarding pass.", 0),
        ("rem_05", "jrn_01", "TRAVEL_DAY", "2026-11-15 11:30:00", "Flight Departure Today", "Travel Day! Your flight UR 446 departs at 17:30. Arrive at Entebbe Airport by 14:30 (3 hours prior) for security screening.", 0)
    ]
    for rid, jid, rtype, sched, title, msg, deliv in reminders:
        db.execute(
            "INSERT OR IGNORE INTO journey_reminders (id, journey_id, reminder_type, scheduled_for, title, message, is_delivered) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (rid, jid, rtype, sched, title, msg, deliv)
        )

    # 7. Sample Recent Rides
    _seed_demo_rides(db)
    db.execute(
        """INSERT OR IGNORE INTO reward_point_awards (ride_id, passenger_id, points)
           SELECT id, passenger_id, 100 FROM rides
           WHERE (id GLOB 'ride_0[1-9]' OR id = 'ride_10')
             AND status = 'COMPLETED' AND payment_status = 'PAID'"""
    )

    # 8. Sample Saved Routes
    _seed_saved_routes(db)

    # Audit log entry
    db.execute(
        "INSERT OR IGNORE INTO audit_logs (id, user_id, action, resource_type, resource_id, details) VALUES (?, ?, ?, ?, ?, ?)",
        ("aud_init", "usr_admin_01", "SYSTEM_SEED", "DATABASE", "ALL", "Initialised seed demo data with 5 roles and Ugandan transportation fixtures")
    )

    print("RideEasy database seeded successfully.")

def _seed_demo_rides(db):
    now = datetime.now()
    rides = [
        ("ride_01", "usr_pass_01", "usr_driver_01", "ECONOMY", "Acacia Mall, Kisementi, Kampala", 0.3340, 32.5890, "Entebbe International Airport Terminal", 0.0424, 32.4435, 42.5, 85000, 85000, "MTN_MOMO", "PAID", "COMPLETED", 1, (now - timedelta(days=6, hours=3)).strftime("%Y-%m-%d %H:%M:%S")),
        ("ride_02", "usr_pass_01", "usr_driver_01", "ECONOMY", "Plot 14 Acacia Avenue, Kololo", 0.3300, 32.5900, "Garden City Mall, Yusuf Lule Road", 0.3200, 32.5870, 3.2, 7500, 7500, "CASH", "PAID", "COMPLETED", 0, (now - timedelta(days=5, hours=4)).strftime("%Y-%m-%d %H:%M:%S")),
        ("ride_03", "usr_pass_01", "usr_driver_01", "COMFORT", "Victoria Towers, Nakasero Road", 0.3200, 32.5780, "Lugogo Mall / Shoprite / Game", 0.3275, 32.6105, 5.2, 14000, 14000, "AIRTEL_MONEY", "PAID", "COMPLETED", 0, (now - timedelta(days=4, hours=5)).strftime("%Y-%m-%d %H:%M:%S")),
        ("ride_04", "usr_pass_01", "usr_driver_01", "ECONOMY", "Makerere University Main Gate", 0.3312, 32.5702, "Acacia Mall, Kololo", 0.3340, 32.5890, 4.5, 11500, 11500, "CASH", "PAID", "COMPLETED", 0, (now - timedelta(days=3, hours=6)).strftime("%Y-%m-%d %H:%M:%S")),
        ("ride_05", "usr_pass_01", "usr_driver_01", "PREMIUM", "Plot 14 Acacia Avenue, Kololo", 0.3300, 32.5900, "Entebbe International Airport (EBB)", 0.0424, 32.4435, 42.5, 95000, 95000, "CARD", "PAID", "COMPLETED", 1, (now - timedelta(days=3, hours=1)).strftime("%Y-%m-%d %H:%M:%S")),
        ("ride_06", "usr_pass_01", "usr_driver_01", "COMFORT", "Kampala City Centre (Posta Uganda)", 0.3136, 32.5811, "Ntinda Complex / Capital Shoppers", 0.3542, 32.6120, 6.8, 16500, 16500, "MTN_MOMO", "PAID", "COMPLETED", 0, (now - timedelta(days=2, hours=3)).strftime("%Y-%m-%d %H:%M:%S")),
        ("ride_07", "usr_pass_01", "usr_driver_01", "ECONOMY", "Garden City Mall, Yusuf Lule Road", 0.3195, 32.5912, "Greenhill Academy Kibuli", 0.3060, 32.5985, 4.8, 12500, 12500, "CASH", "PAID", "COMPLETED", 0, (now - timedelta(days=1, hours=7)).strftime("%Y-%m-%d %H:%M:%S")),
        ("ride_08", "usr_pass_01", "usr_driver_01", "COMFORT", "Victoria Towers, Nakasero Road", 0.3200, 32.5780, "Acacia Mall, Kisementi, Kololo", 0.3340, 32.5890, 4.2, 13000, 13000, "AIRTEL_MONEY", "PAID", "COMPLETED", 0, (now - timedelta(days=1, hours=2)).strftime("%Y-%m-%d %H:%M:%S")),
        ("ride_09", "usr_pass_01", "usr_driver_01", "ECONOMY", "Acacia Mall, Kisementi, Kololo", 0.3340, 32.5890, "Kampala City Centre (Posta)", 0.3136, 32.5811, 3.8, 9500, 9500, "MTN_MOMO", "PAID", "COMPLETED", 0, (now - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S")),
        ("ride_10", "usr_pass_01", "usr_driver_01", "COMFORT", "Plot 14 Acacia Avenue, Kololo", 0.3300, 32.5900, "Victoria Towers, Nakasero Road", 0.3200, 32.5780, 4.2, 12000, 12000, "CASH", "PAID", "COMPLETED", 0, (now - timedelta(minutes=45)).strftime("%Y-%m-%d %H:%M:%S")),
    ]
    for r_id, p_id, d_id, cat, p_addr, p_lat, p_lng, d_addr, d_lat, d_lng, dist, efare, ffare, pmethod, pstat, stat, is_air, cr_at in rides:
        db.execute(
            """INSERT OR IGNORE INTO rides
            (id, passenger_id, driver_id, category, pickup_address, pickup_lat, pickup_lng, destination_address, destination_lat, destination_lng, estimated_distance_km, estimated_fare_ugx, final_fare_ugx, payment_method, payment_status, status, is_airport_ride, created_at) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (r_id, p_id, d_id, cat, p_addr, p_lat, p_lng, d_addr, d_lat, d_lng, dist, efare, ffare, pmethod, pstat, stat, is_air, cr_at)
        )

    # Seed initial 5-star rating for ride_01
    db.execute(
        """INSERT OR IGNORE INTO ride_ratings 
        (id, ride_id, passenger_id, driver_id, rating, review, created_at) 
        VALUES (?, ?, ?, ?, ?, ?, datetime('now', '-2 days'))""",
        ("rate_01", "ride_01", "usr_pass_01", "usr_driver_01", 5, "Excellent trip to Entebbe Airport! Driver David was punctual and driving was super smooth.")
    )

def _seed_saved_routes(db):
    sample_routes = [
        ("route_01", "usr_pass_01", "Home to Office", "Plot 14 Acacia Avenue, Kololo", "Victoria Towers, Nakasero Road", "ECONOMY"),
        ("route_02", "usr_pass_01", "Office to Acacia Mall", "Victoria Towers, Nakasero Road", "Acacia Mall, Kisementi, Kololo", "BODA"),
        ("route_03", "usr_pass_01", "Home to Entebbe Airport", "Plot 14 Acacia Avenue, Kololo", "Entebbe International Airport (EBB)", "COMFORT")
    ]
    for r_id, p_id, r_name, p_addr, d_addr, cat in sample_routes:
        db.execute(
            """INSERT OR IGNORE INTO saved_routes 
            (id, passenger_id, name, pickup_address, destination_address, category) 
            VALUES (?, ?, ?, ?, ?, ?)""",
            (r_id, p_id, r_name, p_addr, d_addr, cat)
        )


def _remove_legacy_demo_data(db):
    """Remove the built-in demo identities and their linked sample records."""
    demo_emails = (
        "admin@rideeasy.ug",
        "passenger@rideeasy.ug",
        "driver@rideeasy.ug",
        "school@rideeasy.ug",
        "travel@rideeasy.ug",
    )
    demo_ids = "SELECT id FROM users WHERE email IN (?, ?, ?, ?, ?)"
    demo_ride_ids = "SELECT id FROM rides WHERE passenger_id IN (" + demo_ids + ")"
    demo_flight_request_ids = (
        "SELECT id FROM flight_requests WHERE passenger_id IN (" + demo_ids + ")"
    )
    operations = [
        (
            """UPDATE school_transport_requests
               SET assigned_driver_id = NULL, assigned_vehicle_id = NULL
               WHERE assigned_driver_id IN (""" + demo_ids + """)
                  OR assigned_vehicle_id IN (
                      SELECT id FROM vehicles WHERE driver_id IN (""" + demo_ids + """)
                  )""",
            demo_emails * 2,
        ),
        (
            "UPDATE flight_requests SET assigned_company_id = NULL WHERE assigned_company_id IN (" + demo_ids + ")",
            demo_emails,
        ),
        (
            """DELETE FROM ride_ratings
               WHERE passenger_id IN (""" + demo_ids + """)
                  OR driver_id IN (""" + demo_ids + """)""",
            demo_emails * 2,
        ),
        (
            """DELETE FROM reward_point_awards
               WHERE passenger_id IN (""" + demo_ids + """)
                  OR ride_id IN (""" + demo_ride_ids + """)""",
            demo_emails * 2,
        ),
        (
            """DELETE FROM flight_quotations
               WHERE travel_company_id IN (""" + demo_ids + """)
                  OR request_id IN (""" + demo_flight_request_ids + """)""",
            demo_emails * 2,
        ),
        (
            """DELETE FROM flight_bookings
               WHERE travel_company_id IN (""" + demo_ids + """)
                  OR request_id IN (""" + demo_flight_request_ids + """)""",
            demo_emails * 2,
        ),
        (
            """DELETE FROM payment_ledger
               WHERE recipient_id IN (""" + demo_ids + """)
                  OR payment_id IN (
                      SELECT id FROM payment_transactions
                      WHERE passenger_id IN (""" + demo_ids + """)
                         OR ride_id IN (""" + demo_ride_ids + """)
                  )""",
            demo_emails * 3,
        ),
        (
            """DELETE FROM sms_messages WHERE payment_id IN (
                   SELECT id FROM payment_transactions
                   WHERE passenger_id IN (""" + demo_ids + """)
                      OR ride_id IN (""" + demo_ride_ids + """)
               )""",
            demo_emails * 2,
        ),
        (
            """DELETE FROM payment_transactions
               WHERE passenger_id IN (""" + demo_ids + """)
                  OR ride_id IN (""" + demo_ride_ids + """)""",
            demo_emails * 2,
        ),
        (
            """UPDATE rides SET related_journey_id = NULL
               WHERE related_journey_id IN (
                   SELECT id FROM confirmed_journeys WHERE passenger_id IN (""" + demo_ids + """)
               )""",
            demo_emails,
        ),
        (
            "UPDATE rides SET driver_id = NULL WHERE driver_id IN (" + demo_ids + ")",
            demo_emails,
        ),
        (
            "DELETE FROM vehicles WHERE driver_id IN (" + demo_ids + ")",
            demo_emails,
        ),
        (
            "DELETE FROM users WHERE email IN (?, ?, ?, ?, ?)",
            demo_emails,
        ),
    ]
    db.execute_transaction(operations)
