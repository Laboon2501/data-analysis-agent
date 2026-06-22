PRAGMA foreign_keys = OFF;

DROP TABLE IF EXISTS order_items;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS users;
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS regions;
DROP TABLE IF EXISTS channels;

PRAGMA foreign_keys = ON;

CREATE TABLE regions (
    id INTEGER PRIMARY KEY,
    region_name TEXT NOT NULL,
    country TEXT NOT NULL
);

CREATE TABLE channels (
    id INTEGER PRIMARY KEY,
    channel_name TEXT NOT NULL,
    channel_type TEXT NOT NULL
);

CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    user_name TEXT NOT NULL,
    signup_month TEXT NOT NULL,
    region_id INTEGER NOT NULL,
    acquisition_channel_id INTEGER NOT NULL,
    FOREIGN KEY(region_id) REFERENCES regions(id),
    FOREIGN KEY(acquisition_channel_id) REFERENCES channels(id)
);

CREATE TABLE products (
    id INTEGER PRIMARY KEY,
    product_name TEXT NOT NULL,
    category TEXT NOT NULL,
    unit_price REAL NOT NULL
);

CREATE TABLE orders (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    order_month TEXT NOT NULL,
    order_date TEXT NOT NULL,
    region_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    region_name TEXT NOT NULL,
    channel_name TEXT NOT NULL,
    category TEXT NOT NULL,
    gmv REAL NOT NULL,
    sales_amount REAL NOT NULL,
    quantity INTEGER NOT NULL,
    order_count INTEGER NOT NULL,
    status TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id),
    FOREIGN KEY(region_id) REFERENCES regions(id),
    FOREIGN KEY(channel_id) REFERENCES channels(id)
);

CREATE TABLE order_items (
    id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    category TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    unit_price REAL NOT NULL,
    item_gmv REAL NOT NULL,
    FOREIGN KEY(order_id) REFERENCES orders(id),
    FOREIGN KEY(product_id) REFERENCES products(id)
);

INSERT INTO regions (id, region_name, country)
VALUES
    (1, 'North', 'US'),
    (2, 'South', 'US'),
    (3, 'East', 'US'),
    (4, 'West', 'US');

INSERT INTO channels (id, channel_name, channel_type)
VALUES
    (1, 'Organic Search', 'digital'),
    (2, 'Paid Social', 'digital'),
    (3, 'Email', 'owned'),
    (4, 'Marketplace', 'partner');

INSERT INTO users (id, user_name, signup_month, region_id, acquisition_channel_id)
VALUES
    (1, 'Avery', '2025-01', 1, 1),
    (2, 'Blake', '2025-02', 2, 2),
    (3, 'Casey', '2025-03', 3, 3),
    (4, 'Devon', '2025-04', 4, 4),
    (5, 'Emery', '2025-05', 1, 2),
    (6, 'Finley', '2025-06', 2, 1),
    (7, 'Gray', '2025-07', 3, 4),
    (8, 'Harper', '2025-08', 4, 3);

INSERT INTO products (id, product_name, category, unit_price)
VALUES
    (1, 'Trail Backpack', 'Outdoor', 89.0),
    (2, 'Insulated Bottle', 'Outdoor', 28.0),
    (3, 'Desk Lamp', 'Home', 42.0),
    (4, 'Linen Sheet Set', 'Home', 120.0),
    (5, 'Wireless Earbuds', 'Electronics', 150.0),
    (6, 'USB-C Hub', 'Electronics', 65.0),
    (7, 'Yoga Mat', 'Fitness', 45.0),
    (8, 'Resistance Band Set', 'Fitness', 32.0);

INSERT INTO orders (
    id,
    user_id,
    order_month,
    order_date,
    region_id,
    channel_id,
    region_name,
    channel_name,
    category,
    gmv,
    sales_amount,
    quantity,
    order_count,
    status
)
VALUES
    (1, 1, '2025-07', '2025-07-04', 1, 1, 'North', 'Organic Search', 'Outdoor', 178.0, 169.1, 2, 1, 'paid'),
    (2, 2, '2025-08', '2025-08-12', 2, 2, 'South', 'Paid Social', 'Home', 162.0, 153.9, 2, 1, 'paid'),
    (3, 3, '2025-09', '2025-09-16', 3, 3, 'East', 'Email', 'Electronics', 215.0, 204.25, 2, 1, 'paid'),
    (4, 4, '2025-10', '2025-10-02', 4, 4, 'West', 'Marketplace', 'Fitness', 122.0, 115.9, 3, 1, 'paid'),
    (5, 5, '2025-11', '2025-11-09', 1, 2, 'North', 'Paid Social', 'Home', 240.0, 228.0, 2, 1, 'paid'),
    (6, 6, '2025-12', '2025-12-18', 2, 1, 'South', 'Organic Search', 'Outdoor', 206.0, 195.7, 3, 1, 'paid'),
    (7, 7, '2026-01', '2026-01-07', 3, 4, 'East', 'Marketplace', 'Electronics', 300.0, 285.0, 2, 1, 'paid'),
    (8, 8, '2026-02', '2026-02-14', 4, 3, 'West', 'Email', 'Fitness', 154.0, 146.3, 4, 1, 'paid'),
    (9, 1, '2026-03', '2026-03-03', 1, 1, 'North', 'Organic Search', 'Outdoor', 267.0, 253.65, 3, 1, 'paid'),
    (10, 2, '2026-04', '2026-04-21', 2, 2, 'South', 'Paid Social', 'Home', 282.0, 267.9, 3, 1, 'paid'),
    (11, 3, '2026-05', '2026-05-06', 3, 3, 'East', 'Email', 'Electronics', 365.0, 346.75, 3, 1, 'paid'),
    (12, 4, '2026-06', '2026-06-10', 4, 4, 'West', 'Marketplace', 'Fitness', 199.0, 189.05, 5, 1, 'paid'),
    (13, 5, '2026-06', '2026-06-11', 1, 1, 'North', 'Organic Search', 'Electronics', 430.0, 408.5, 3, 1, 'paid'),
    (14, 6, '2026-05', '2026-05-22', 2, 3, 'South', 'Email', 'Outdoor', 295.0, 280.25, 4, 1, 'paid'),
    (15, 7, '2026-04', '2026-04-25', 3, 4, 'East', 'Marketplace', 'Home', 324.0, 307.8, 3, 1, 'paid'),
    (16, 8, '2026-03', '2026-03-19', 4, 2, 'West', 'Paid Social', 'Fitness', 186.0, 176.7, 5, 1, 'paid');

INSERT INTO order_items (id, order_id, product_id, category, quantity, unit_price, item_gmv)
VALUES
    (1, 1, 1, 'Outdoor', 2, 89.0, 178.0),
    (2, 2, 3, 'Home', 1, 42.0, 42.0),
    (3, 2, 4, 'Home', 1, 120.0, 120.0),
    (4, 3, 5, 'Electronics', 1, 150.0, 150.0),
    (5, 3, 6, 'Electronics', 1, 65.0, 65.0),
    (6, 4, 7, 'Fitness', 2, 45.0, 90.0),
    (7, 4, 8, 'Fitness', 1, 32.0, 32.0),
    (8, 5, 4, 'Home', 2, 120.0, 240.0),
    (9, 6, 1, 'Outdoor', 2, 89.0, 178.0),
    (10, 6, 2, 'Outdoor', 1, 28.0, 28.0),
    (11, 7, 5, 'Electronics', 2, 150.0, 300.0),
    (12, 8, 7, 'Fitness', 2, 45.0, 90.0),
    (13, 8, 8, 'Fitness', 2, 32.0, 64.0),
    (14, 9, 1, 'Outdoor', 3, 89.0, 267.0),
    (15, 10, 4, 'Home', 2, 120.0, 240.0),
    (16, 10, 3, 'Home', 1, 42.0, 42.0),
    (17, 11, 5, 'Electronics', 2, 150.0, 300.0),
    (18, 11, 6, 'Electronics', 1, 65.0, 65.0),
    (19, 12, 7, 'Fitness', 3, 45.0, 135.0),
    (20, 12, 8, 'Fitness', 2, 32.0, 64.0),
    (21, 13, 5, 'Electronics', 2, 150.0, 300.0),
    (22, 13, 6, 'Electronics', 2, 65.0, 130.0),
    (23, 14, 1, 'Outdoor', 3, 89.0, 267.0),
    (24, 14, 2, 'Outdoor', 1, 28.0, 28.0),
    (25, 15, 4, 'Home', 2, 120.0, 240.0),
    (26, 15, 3, 'Home', 2, 42.0, 84.0),
    (27, 16, 7, 'Fitness', 2, 45.0, 90.0),
    (28, 16, 8, 'Fitness', 3, 32.0, 96.0);

