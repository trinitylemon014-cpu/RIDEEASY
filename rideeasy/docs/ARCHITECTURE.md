# RideEasy Platform Architecture
**MOVE. TRAVEL. ARRIVE.**
**Engineering by Emtrixz Technology Company**

## Overview
RideEasy is a unified African transportation platform serving urban ride-hailing, institutional school bus charters, verified flight booking assistance, and scheduled airport transfers.

```
                              [Client / Browser / PWA / Mobile Wrapper]
                                                 │
                                                 ▼
                                     [Flask Application Server]
                                                 │
         ┌───────────────────┬───────────────────┼───────────────────┬───────────────────┐
         │                   │                   │                   │                   │
         ▼                   ▼                   ▼                   ▼                   ▼
    [Passenger]          [Driver]            [School]          [Travel Agency]        [Admin]
     Blueprint           Blueprint           Blueprint            Blueprint          Blueprint
         │                   │                   │                   │                   │
         └───────────────────┴───────────────────┼───────────────────┴───────────────────┘
                                                 │
                                 ┌───────────────┴───────────────┐
                                 │       Services Layer          │
                                 │  - AuthService (RBAC)         │
                                 │  - PricingService (Tariffs)   │
                                 │  - MapService (Distances)     │
                                 │  - ReminderService (5-Tier)   │
                                 │  - PaymentService (Gateways)  │
                                 └───────────────┬───────────────┘
                                                 │
                                 ┌───────────────┴───────────────┐
                                 │       Repository Layer        │
                                 │  - Turso libSQL Sync Client   │
                                 │  - SQLite Local Dev Fallback  │
                                 └───────────────────────────────┘
```

## Blueprints and Routing Architecture
1. **`main` (`/`)**: Public homepage, Fare Estimator widget, About us, Trust & Safety standards, Pricing tables, Contact desk.
2. **`auth` (`/auth`)**: Registration (Passenger, Driver, School), Login, Logout, Password Recovery, and 1-Click Demo Persona Switchers.
3. **`passenger` (`/passenger`)**: Dashboard, Book Ride, Active Trip Tracker, Trip History, Printable Official Receipt, Flight Booking Inquiries, Confirmed Journeys & Reminders.
4. **`driver` (`/driver`)**: Dashboard, Online/Offline status switch, Incoming dispatch queue, sequential status transitions, earnings ledger, compliance verification.
5. **`school` (`/school`)**: Institutional dashboard, Coaster (30 seats) & Bus (60 seats) charter bookings, operator allocation, invoice tracking.
6. **`travel_partner` (`/travel`)**: Accredited agency console, assigned passenger inquiries, quotation builder, genuine airline PNR confirmation.
7. **`admin` (`/admin`)**: Operations oversight, user management, driver vetting, school request dispatch, flight routing, pricing configuration, tamper-evident audit logs.
8. **`api` (`/api`)**: JSON endpoints for live fare calculation, landmark coordinates, and real-time trip status polling.

## Design Constitution & Frontend Rules
- **Color Palette**: Pure monochrome `#000000`, `#111111`, `#1C1C1C`, `#FFFFFF`, `#F7F7F7`, `#E5E5E5`, `#777777`.
- **Icons**: 100% black SVG icons (stroke width 1.75). Strict ban on emojis and colourful badge pills.
- **Zero-Pill Discipline**: Metadata displayed as unboxed text separated by subtle typographic middle dots (`·`).
- **Mobile-First Responsive Layout**: All forms and buttons adhere to touch target minimums (>= 44px).
