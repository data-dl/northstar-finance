"""The invented household every generated file describes.

Nothing here is derived from a real person. Names, employers, merchants, account numbers and
prices were made up for the sample dataset; keep them consistent with config.yaml (the keyword
lists there are written against these merchant strings) and with the hand-written commentary in
templates/ (which quotes a few of these figures).
"""
import datetime as dt

# ------------------------------------------------------------------ calendar
BANK_START = dt.date(2024, 7, 1)      # first day of bank history
BANK_END = dt.date(2026, 8, 31)       # last complete statement on file
CARD_EXPORT = dt.date(2026, 9, 1)     # the day the card CSVs were pulled
AS_OF = dt.date(2026, 9, 12)          # "today" for the sample: alerts run up to the day before
FIRST_PAYDAY = dt.date(2024, 7, 12)   # biweekly Fridays from here

# ------------------------------------------------------------------ people
OWNER = "Casey Morgan"
VENMO_HANDLE = "@Casey-Morgan-12"
FAMILY_TRANSFER = "Zelle to Linda Morgan"          # config.entities.family_desc_match
LOAN_BORROWER = "Alex Carver"
LOAN_DATE = dt.date(2026, 8, 20)
LOAN_PRINCIPAL = 3500.00

# Venmo counterparties by era. Rent went to roommates until the move to Lakeview.
RENT_ROOMMATES = [  # name, first month, last month, monthly rent
    ("Priya Natarajan", dt.date(2017, 1, 1), dt.date(2018, 12, 1), 900.00),
    ("Marcus Bell", dt.date(2019, 1, 1), dt.date(2020, 10, 1), 640.00),
    ("Dana Whitfield", dt.date(2020, 11, 1), dt.date(2021, 12, 1), 500.00),
]
SETTLED_LOAN = "T. Okonkwo"            # the 2023 loan, repaid outside Venmo
FRUIT_VENDOR = "Lakeview Fruit Cart"   # config.entities.fruit_vendor
MOVIE_BUDDY = "Jo Park"                # config.entities.movie_buddy
MEAL_FRIENDS = ["Sam Iyer", "Alex Carver", "Priya Natarajan", "Dana Whitfield"]
EVENT_FRIEND = "Jordan Reyes"          # config.entities.event_recipients_venmo

# ------------------------------------------------------------------ pay
PAY_NET = 1970.68                      # config.pay.per_check_net
PAYROLL_DESC = "Lakeview County Payroll"
PAYROLL_ORIG = "Deposit LAKEVIEW COUNTY PAYROLL / TYPE: DIRECT DEP ID: XXXXXX4410 CO: LAKEVIEW COUNTY %% ACH ECC PPD"

NONSALARY_INCOME = [  # date, description, original description, amount
    (dt.date(2026, 2, 13), "Lakeview County AP Reimb", "Deposit LAKEVIEW COUNTY AP REIMB / TYPE: VENDOR PAY CO: LAKEVIEW COUNTY", 318.40),
    (dt.date(2026, 4, 22), "State Tax Refund", "Deposit STATE TAX REFUND / TYPE: TAX REF CO: STATE TREASURER", 612.00),
    (dt.date(2026, 7, 17), "Streamco Settlement Fund", "Deposit STREAMCO SETTLEMENT FUND / TYPE: SETTLEMENT CO: STREAMCO CLAIMS", 1940.00),
]

# ------------------------------------------------------------------ cards
CARDS = {  # last four -> (name, Chase export prefix)
    "4417": "Chase Freedom",
    "8802": "Chase Prime Visa",
}
FREEDOM, PRIME = "4417", "8802"
CARD_PIVOT = dt.date(2026, 5, 19)      # everyday spending moved onto the Freedom for points
COOKING_STARTED = dt.date(2026, 4, 6)
CAT_ADOPTED = dt.date(2026, 5, 20)
FREEDOM_CLOSE_DAY, FREEDOM_DUE_DAY = 19, 16     # statement closes on the 19th, autopays on the 16th
PRIME_CLOSE_DAY, PRIME_DUE_DAY = 10, 7

# ------------------------------------------------------------------ bank fixtures
RENT_OLD = ("Old Rent Portal", "Withdrawal OLD RENT PORTAL / TYPE: RENT CO: OLD RENT PORTAL %% ACH ECC WEB", 1240.00)
RENT_NEW = ("Havenbrook Residential", "Withdrawal HAVENBROOK RESIDENTIAL / TYPE: RENT ID: XXXXXX2210 CO: HAVENBROOK RES %% ACH ECC PPD", 1285.00)
RENT_SWITCH = dt.date(2024, 9, 1)

# Corner-store menu: everything sits on a $0.25 grid and the store charges 7% tax, which is what
# lets the dashboard read tickets back into baskets. The first item is the energy drink the
# Amazon bulk-buy is compared against.
DELI = "FOURTH STREET MARKET"
DELI_TAX = 0.07
DELI_ITEMS = {"Red Bull": 3.25, "Clif Bar": 1.75, "coffee": 1.50, "water": 1.25, "chips": 2.00,
              "sandwich": 6.50, "gum": 1.25, "banana": 0.75}
# (basket, weight): the signature basket dominates, as the commentary says
DELI_BASKETS = [
    (("Red Bull", "Clif Bar"), 46), (("Red Bull",), 24), (("Clif Bar",), 5), (("coffee",), 6),
    (("Red Bull", "chips"), 4), (("water",), 3), (("sandwich",), 4), (("coffee", "Clif Bar"), 3),
    (("gum",), 2), (("banana", "coffee"), 2), (("Red Bull", "Clif Bar", "water"), 1),
]

# Other corner stores: (description, visits per month, ticket low, ticket high)
SNACK_STORES = [
    ("RIVERSIDE QUICK STOP", 6.6, 2.10, 7.90),
    ("ELM & 9TH CONVENIENCE", 2.5, 2.50, 8.50),
    ("NORTHGATE EXPRESS MART", 1.6, 3.00, 9.00),
    ("BLUE LINE SNACKS", 2.0, 2.00, 5.50),
    ("CAMPUS CORNER DELI", 1.0, 3.50, 7.50),
    ("LAKEVIEW GAS & GO", 0.7, 3.00, 11.00),
    ("SUNRISE BODEGA", 0.5, 4.00, 12.00),
]

# Restaurants: (description, visits per month, ticket low, ticket high, Chase category)
RESTAURANT_SCALE = 0.7
RESTAURANTS = [
    ("CHIPOTLE 2291", 2.3, 10.40, 15.80, "Food & Drink"),
    ("SUNFIRE TAQUERIA", 1.5, 12.00, 22.00, "Food & Drink"),
    ("PANERA BREAD #601442", 1.7, 8.90, 14.20, "Food & Drink"),
    ("BASIL & RYE", 0.8, 17.00, 28.00, "Food & Drink"),
    ("GOLDEN WOK", 1.0, 11.50, 18.90, "Food & Drink"),
    ("LAKEVIEW PHO HOUSE", 0.7, 14.00, 24.00, "Food & Drink"),
    ("DOMINO'S 5512", 0.9, 9.99, 16.48, "Food & Drink"),
    ("CAFE LUMEN", 2.0, 3.75, 7.50, "Food & Drink"),
    ("STARBUCKS #22910", 1.8, 4.15, 6.85, "Food & Drink"),
    ("WENDY'S #4471", 0.7, 6.20, 10.90, "Food & Drink"),
    ("SHAKE SHACK 1120", 0.3, 12.40, 18.60, "Food & Drink"),
]

GROCERS = [
    ("KROGER #445", 3.7, 18.00, 52.00, "Groceries"),
    ("TRADER JOE'S #712", 2.7, 19.00, 48.00, "Groceries"),
    ("ALDI 71034", 1.7, 14.00, 34.00, "Groceries"),
    ("LAKEVIEW FARMERS MARKET", 1.2, 8.00, 18.00, "Groceries"),
    ("COSTCO WHSE #1187", 0.15, 62.00, 98.00, "Groceries"),
]

DRUGSTORES = [
    ("CVS/PHARMACY #8812", 0.9, 7.40, 24.90, "Health & Wellness"),
    ("WALGREENS #3310", 0.5, 6.80, 22.40, "Health & Wellness"),
]

ENTERTAINMENT = [
    ("AMC THEATRES #2255", 0.85, 14.50, 21.00, "Entertainment"),
    ("CORNER BOOKS LAKEVIEW", 0.55, 9.50, 24.00, "Entertainment"),
    ("BANDCAMP", 0.4, 6.00, 12.00, "Entertainment"),
    ("RIVERSIDE CINEMA", 0.35, 12.00, 19.50, "Entertainment"),
]

TRANSIT_TAPS_PER_MONTH = 4.5
TRANSIT_TAP = ("LAKEVIEW TRANSIT AUTH", 2.75, "Travel")
LYFT = ("LYFT *RIDE", 1.2, 8.50, 18.90, "Travel")
PARKING = ("LAKEVIEW PARKING", 1.0, 6.00, 10.00, "Travel")

TARGET = ("TARGET 00028215", 1.1, 22.00, 58.00, "Shopping")

# Card-paid subscriptions: (description, amount, day of month, card, first month, last month or None)
SUBSCRIPTIONS = [
    ("SPOTIFY USA", 11.99, 14, FREEDOM, dt.date(2024, 7, 1), None),
    ("NETFLIX.COM", 15.49, 22, FREEDOM, dt.date(2024, 7, 1), dt.date(2025, 10, 1)),
    ("NETFLIX.COM", 17.99, 22, FREEDOM, dt.date(2025, 11, 1), None),          # the price creep
    ("APPLE.COM/BILL", 2.99, 11, PRIME, dt.date(2024, 7, 1), None),
    ("GOOGLE *GOOGLE ONE", 2.99, 3, PRIME, dt.date(2024, 7, 1), None),
    ("NYTIMES*NYT DIGITAL", 4.00, 9, PRIME, dt.date(2024, 7, 1), None),
    ("PELOTON APP", 12.99, 19, FREEDOM, dt.date(2025, 9, 1), None),
    ("MINT MOBILE", 30.00, 30, FREEDOM, dt.date(2024, 7, 1), None),
    ("BLUEPINE HOSTING", 13.82, 6, PRIME, dt.date(2024, 7, 1), None),
    ("AUDIBLE", 14.95, 15, PRIME, dt.date(2025, 3, 1), dt.date(2025, 12, 1)),   # ended
    ("HULU", 9.99, 30, FREEDOM, dt.date(2025, 2, 1), dt.date(2025, 9, 1)),      # ended
    ("LEMONADE INSURANCE", 12.00, 14, FREEDOM, dt.date(2024, 8, 1), dt.date(2025, 6, 1)),  # ended
]
ANNUALS = [  # description, amount, dates, card
    ("AMAZON PRIME*2K4LT9Q", 139.00, [dt.date(2025, 6, 12), dt.date(2026, 6, 12)], PRIME),
    ("MICROSOFT*365 PERSONAL", 99.99, [dt.date(2025, 3, 4), dt.date(2026, 3, 4)], PRIME),
    ("AAA ACG RENEWAL", 108.00, [dt.date(2024, 10, 18), dt.date(2025, 10, 18)], FREEDOM),
    ("COSTCO *ANNUAL RENEWAL", 65.00, [dt.date(2024, 10, 5), dt.date(2025, 10, 5)], FREEDOM),
    ("DOMAINWORKS", 26.94, [dt.date(2025, 6, 1), dt.date(2025, 9, 1), dt.date(2025, 12, 1), dt.date(2026, 3, 1), dt.date(2026, 6, 1)], PRIME),
    ("RIDGELINE RX MAIL ORDER", 192.00, [dt.date(2024, 10, 14), dt.date(2025, 1, 14), dt.date(2025, 4, 14), dt.date(2025, 7, 14),
                                          dt.date(2025, 10, 14), dt.date(2026, 1, 14), dt.date(2026, 4, 14), dt.date(2026, 7, 14)], PRIME),
    ("LAKEVIEW REC CENTER", 85.00, [dt.date(2024, 9, 3), dt.date(2025, 1, 7), dt.date(2025, 5, 6), dt.date(2025, 9, 2), dt.date(2026, 1, 6)], FREEDOM),
    ("LAKEVIEW AQUATICS", 149.00, [dt.date(2026, 8, 22)], FREEDOM),
    ("LAKEVIEW DENTAL GROUP", 308.00, [dt.date(2024, 12, 9)], FREEDOM),
    ("LAKEVIEW DENTAL GROUP", 204.00, [dt.date(2025, 6, 16)], FREEDOM),
    ("LAKEVIEW DENTAL GROUP", 100.00, [dt.date(2026, 7, 21)], FREEDOM),
    ("URGENT CARE OF LAKEVIEW", 148.00, [dt.date(2026, 2, 11)], FREEDOM),
    ("CVS MINUTECLINIC", 89.00, [dt.date(2025, 11, 3)], FREEDOM),
    ("LAKEVIEW PARKING VIOLATIONS", 47.50, [dt.date(2025, 3, 12), dt.date(2025, 9, 4)], FREEDOM),
    ("LAKEVIEW PUBLIC LIBRARY FINE", 4.00, [dt.date(2025, 2, 3), dt.date(2025, 8, 11), dt.date(2026, 3, 30)], FREEDOM),
    ("LAKEVIEW PUBLIC LIBRARY FRIENDS", 30.00, [dt.date(2024, 11, 2), dt.date(2025, 11, 1)], FREEDOM),
    ("CITY MUSEUM OF ART", 21.00, [dt.date(2024, 10, 12), dt.date(2025, 4, 5), dt.date(2025, 10, 11), dt.date(2026, 5, 2)], FREEDOM),
    ("AMTRAK .COM", 128.00, [dt.date(2024, 11, 26), dt.date(2025, 7, 3), dt.date(2025, 12, 23)], FREEDOM),
    ("AMTRAK .COM", 88.00, [dt.date(2026, 8, 1)], FREEDOM),
    ("SHELL OIL 57442", 20.71, [dt.date(2024, 8, 9), dt.date(2024, 11, 27), dt.date(2025, 3, 2), dt.date(2025, 7, 4), dt.date(2025, 9, 20),
                               dt.date(2025, 12, 24), dt.date(2026, 3, 8), dt.date(2026, 6, 20), dt.date(2026, 8, 2)], FREEDOM),
    ("TURBOTAX", 89.00, [dt.date(2025, 3, 22), dt.date(2026, 3, 14)], FREEDOM),
    ("BEST BUY 00012241", 194.49, [dt.date(2025, 2, 15), dt.date(2025, 11, 29)], FREEDOM),
    ("IKEA COLUMBUS", 118.48, [dt.date(2024, 9, 14), dt.date(2025, 5, 3), dt.date(2026, 5, 24)], FREEDOM),
    ("GOODWILL LAKEVIEW", 10.20, [dt.date(2024, 10, 26), dt.date(2025, 1, 18), dt.date(2025, 6, 7), dt.date(2025, 9, 27), dt.date(2026, 2, 21), dt.date(2026, 7, 11)], FREEDOM),
    ("WWW COSTCO COM", 631.46, [dt.date(2026, 6, 14)], FREEDOM),
    ("TARGET 00028215", 101.05, [dt.date(2026, 6, 21)], FREEDOM),
    ("TARGET 00028215", 46.20, [dt.date(2026, 8, 6)], FREEDOM),    # transaction_notes: partly a desk lamp
    ("TARGET 00028215", 27.85, [dt.date(2026, 8, 14)], FREEDOM),   # transaction_notes: allergy medication
]
CARD_RETURNS = [("TARGET 00028215", 24.99, dt.date(2026, 7, 2), FREEDOM)]

# Bank-paid bills: (Description, Original Description, Parent Category, Category, day, amount or None)
BILLS = [
    ("Granite State Servicing", "Withdrawal GRANITE STATE SERVICING / TYPE: STUDENT LN ID: XXXXXX2007 CO: GRANITE STATE SVC %% ACH ECC PPD",
     "Education", "Student Loan", 16, 78.20),
    ("Vantel Fiber", "Withdrawal VANTEL FIBER / TYPE: INTERNET CO: VANTEL FIBER %% ACH ECC WEB", "Bills & Utilities", "Internet", 27, None),
    ("Lakeview Power & Light", "Withdrawal LAKEVIEW PWR & LIGHT / TYPE: ELECTRIC ID: XXXXXX7002 CO: LAKEVIEW PWR LT %% ACH ECC CCD",
     "Bills & Utilities", "Utilities", 20, None),
    ("Northline Gas", "Withdrawal NORTHLINE GAS / TYPE: GAS BILL CO: NORTHLINE GAS %% ACH ECC CCD", "Bills & Utilities", "Utilities", 25, None),
    ("LaundryCard Reload", "Withdrawal LAUNDRYCARD RELOAD / TYPE: PURCHASE CO: LAUNDRYCARD", "Home", "Laundry", 5, 16.00),
]
LIFE_INSURANCE = ("Cornerstone Life Ins Prem", "Withdrawal CORNERSTONE LIFE INS PREM / TYPE: PREMIUM CO: CORNERSTONE LIFE %% ACH ECC PPD",
                  "Financial", "Life Insurance", 20, 93.00)    # quarterly from Jul 2024
STATE_TAX_PAYMENT = (dt.date(2025, 4, 10), "State Tax Payment", "Withdrawal STATE TAX PAYMENT / TYPE: TAX PMT CO: STATE TREASURER", 212.00)

# family support (bank Zelle): $120 a month with a few exceptions
FAMILY_MONTHLY = 120.00
FAMILY_OVERRIDES = {(2024, 12): 240.00, (2025, 8): 0.0, (2025, 12): 240.00, (2026, 3): 180.00}

# ------------------------------------------------------------------ Amazon catalogue
# (description, price, category hint, ASIN). Categories are decided by config keywords at run
# time; the hint only steers how often each item is drawn.
AMAZON_ITEMS = [
    ("Red Bull Energy Drink, 8.4 Fl Oz (24 Pack)", 42.00, "energy", "B0SYN00101"),
    ("Red Bull Sugar Free Energy Drink, 8.4 Fl Oz (12 Pack)", 24.48, "energy", "B0SYN00102"),
    ("CELSIUS Sparkling Orange Fitness Energy Drink, 12 Fl Oz (Pack of 12)", 19.99, "energy", "B0SYN00103"),
    ("Tide PODS Laundry Detergent Soap Pods, Spring Meadow, 81 Count", 21.97, "household", "B0SYN00201"),
    ("Bounty Quick-Size Paper Towels, 8 Family Rolls", 24.99, "household", "B0SYN00202"),
    ("Dawn Ultra Dish Soap, 3 Pack", 11.49, "household", "B0SYN00203"),
    ("Hefty Strong Tall Kitchen Trash Bags, 13 Gallon, 90 Count", 16.98, "household", "B0SYN00204"),
    ("Clorox Disinfecting Wipes, 3 Pack", 12.88, "household", "B0SYN00205"),
    ("Scotch-Brite Non-Scratch Scrub Sponges, 9 Count", 8.49, "household", "B0SYN00206"),
    ("Charmin Ultra Soft Toilet Paper, 18 Mega Rolls", 26.49, "household", "B0SYN00207"),
    ("Dove Men+Care Body Wash, Extra Fresh, 18 oz, 4 Pack", 22.96, "toiletries", "B0SYN00301"),
    ("Head & Shoulders Shampoo and Conditioner Set, 2 Pack", 17.44, "toiletries", "B0SYN00302"),
    ("Degree Men Antiperspirant Deodorant, 4 Count", 15.36, "toiletries", "B0SYN00303"),
    ("CeraVe Daily Moisturizing Lotion, 19 oz", 16.08, "toiletries", "B0SYN00304"),
    ("Gillette Fusion5 Men's Razor Blade Refills, 8 Count", 25.99, "toiletries", "B0SYN00305"),
    ("Oral-B Glide Pro-Health Dental Floss, 6 Pack", 14.49, "toiletries", "B0SYN00306"),
    ("Sensodyne Pronamel Toothpaste, 3 Pack", 15.99, "health", "B0SYN00401"),
    ("Nature Made Vitamin D3 2000 IU, 220 Softgels", 12.42, "health", "B0SYN00402"),
    ("Zyrtec 24 Hour Allergy Relief Tablets, 90 Count", 32.99, "health", "B0SYN00403"),
    ("Band-Aid Brand First Aid Kit, 140 Pieces", 13.97, "health", "B0SYN00404"),
    ("Neutrogena Ultra Sheer Sunscreen SPF 55, 3 oz", 9.97, "health", "B0SYN00405"),
    ("Nissin Chow Mein Noodles, Teriyaki Beef, 4 Ounce (Pack of 8)", 9.97, "grocery", "B0SYN00501"),
    ("Liquid I.V. Electrolyte Drink Mix, Lemon Lime, 16 Sticks", 24.99, "grocery", "B0SYN00502"),
    ("Nature Valley Crunchy Granola Bars, Oats 'n Honey, 24 Count", 11.98, "grocery", "B0SYN00503"),
    ("Quaker Instant Oatmeal Variety Pack, 48 Count", 14.48, "grocery", "B0SYN00504"),
    ("Snyder's of Hanover Mini Pretzels, 16 oz, 3 Pack", 10.47, "grocery", "B0SYN00505"),
    ("Lodge 10.25 Inch Cast Iron Skillet", 24.90, "kitchen", "B0SYN00601"),
    ("OXO Good Grips Mixing Bowl Set, 3 Piece", 29.95, "kitchen", "B0SYN00602"),
    ("Rubbermaid Brilliance Food Storage Container Set, 10 Piece", 39.99, "kitchen", "B0SYN00603"),
    ("Victorinox Fibrox Pro Chef's Knife, 8 Inch", 44.95, "kitchen", "B0SYN00604"),
    ("KitchenAid Classic Nylon Slotted Spatula", 8.99, "kitchen", "B0SYN00605"),
    ("Stainless Steel Colander with Handles, 5 Quart", 18.99, "kitchen", "B0SYN00606"),
    ("Lodge 6 Quart Enameled Dutch Oven", 79.90, "kitchen", "B0SYN00607"),
    ("YETI Rambler 20 oz Tumbler", 35.00, "kitchen", "B0SYN00608"),
    ("Anker USB-C to USB-C Cable, 6 ft, 2 Pack", 12.99, "electronics", "B0SYN00701"),
    ("Anker 65W USB-C Charger, 3 Port", 39.99, "electronics", "B0SYN00702"),
    ("Sony WH-CH520 Wireless Headphones", 49.99, "electronics", "B0SYN00703"),
    ("Anker PowerCore 10000 Portable Power Bank", 21.99, "electronics", "B0SYN00704"),
    ("Logitech MX Keys Mini Wireless Keyboard", 99.99, "electronics", "B0SYN00705"),
    ("Seagate Portable 2TB External Hard Drive", 64.99, "electronics", "B0SYN00706"),
    ("Logitech C920x HD Pro Webcam", 59.99, "electronics", "B0SYN00707"),
    ("Hanes Men's Crew Socks, 12 Pair", 16.00, "clothing", "B0SYN00801"),
    ("Fruit of the Loom Boxer Briefs, 6 Pack", 22.98, "clothing", "B0SYN00802"),
    ("Carhartt Men's Knit Cuffed Beanie", 19.99, "clothing", "B0SYN00803"),
    ("Champion Powerblend Fleece Hoodie", 31.99, "clothing", "B0SYN00804"),
    ("ASICS Gel-Contend 8 Running Shoes", 64.95, "clothing", "B0SYN00805"),
    ("Paperback: A History of the Great Lakes", 18.49, "books", "B0SYN00901"),
    ("Paperback: The Library Book", 12.79, "books", "B0SYN00902"),
    ("Hardcover: Data Pipelines Explained", 34.99, "books", "B0SYN00903"),
    ("Pilot G2 Gel Pens, Fine Point, 12 Count", 11.99, "office", "B0SYN01001"),
    ("Leuchtturm1917 Dotted Notebook, A5", 22.95, "office", "B0SYN01002"),
    ("Post-it Sticky Notes, 3x3, 12 Pads", 12.49, "office", "B0SYN01003"),
    ("Lasko Ceramic Space Heater with Thermostat", 34.99, "home", "B0SYN01101"),
    ("Brightech Sky LED Floor Lamp", 79.99, "home", "B0SYN01102"),
    ("Amazon Basics Velvet Suit Hangers, 50 Pack", 24.99, "home", "B0SYN01103"),
    ("Utopia Bedding Sheet Set, Queen, 4 Piece", 26.99, "home", "B0SYN01104"),
    ("Sterilite 6 Quart Storage Box, 12 Pack", 42.66, "home", "B0SYN01105"),
]
# One-off purchases the commentary refers to (the furnishing wave and the cat setup)
AMAZON_ONE_OFFS = [  # date, description, price, ASIN
    (dt.date(2026, 5, 9), "Zinus Shawn Metal Platform Bed Frame, Queen", 189.99, "B0SYN01201"),
    (dt.date(2026, 6, 6), "NICETOWN Blackout Curtains, 2 Panels, 84 Inch", 49.90, "B0SYN01202"),
    (dt.date(2026, 6, 6), "Amazon Basics Curtain Rod with Cap Finials, 72 to 144 Inch", 23.98, "B0SYN01203"),
    (dt.date(2026, 6, 17), "Sterilite 6 Quart Storage Box, 12 Pack", 42.66, "B0SYN01105"),
    (dt.date(2026, 6, 17), "Brightech Sky LED Floor Lamp", 73.58, "B0SYN01102"),
    (dt.date(2026, 6, 27), "Utopia Bedding Duvet Insert, Queen", 39.99, "B0SYN01204"),
    (dt.date(2026, 6, 27), "Lasko Box Fan, 20 Inch", 26.99, "B0SYN01205"),
    (dt.date(2026, 6, 27), "Command Picture Hanging Strips, 16 Pairs", 23.13, "B0SYN01206"),
    (dt.date(2026, 7, 8), "PETLIBRO Automatic Cat Feeder, 4L", 69.99, "B0SYN01301"),
    (dt.date(2026, 7, 8), "Catit Flower Cat Water Fountain, 3L", 39.99, "B0SYN01302"),
    (dt.date(2026, 7, 12), "Gorilla Grip Cat Litter Trapping Mat, XL, 2 Pack", 32.51, "B0SYN01303"),
    (dt.date(2026, 7, 12), "SmartyKat Skitter Critters Catnip Toy Mice, 3 Pack", 9.98, "B0SYN01304"),
    (dt.date(2026, 7, 26), "VASAGLE Shoe Bench with Storage Shelf", 42.49, "B0SYN01305"),
    (dt.date(2026, 8, 3), "Veken Rug Gripper Pad, 2x3 ft", 12.99, "B0SYN00931"),        # config override -> pets
    (dt.date(2026, 8, 24), "Inaba Churu Cat Treats, Tuna Variety, 20 Tubes", 16.49, "B0SYN01306"),
    (dt.date(2026, 8, 31), "Purina ONE Indoor Advantage Dry Cat Food, 7 lb", 19.98, "B0SYN01307"),
    (dt.date(2026, 8, 31), "Petstages Tower of Tracks Cat Toy", 13.49, "B0SYN01308"),
]

# ------------------------------------------------------------------ Chewy orders
# (date, order id, order total as listed, amount the card was charged after promo credit, status, items)
CHEWY_ORDERS = [
    (dt.date(2026, 5, 22), "5190210441", 56.47, 44.83, "Delivered - Tue, May 26",
     [("Purina ONE", "Indoor Advantage Chicken Recipe Dry Cat Food, 16-lb bag", "38", "48"),
      ("Frisco", "Multi-Cat Unscented Clumping Clay Cat Litter, 40-lb bag", "17", "99")]),
    (dt.date(2026, 6, 3), "5191877002", 31.16, 31.16, "Delivered - Sat, Jun 6",
     [("Fancy Feast", "Classic Pate Variety Pack Canned Cat Food, 3-oz can, case of 24", "24", "48"),
      ("Frisco", "Wand Feather Teaser Cat Toy", "6", "68")]),
    (dt.date(2026, 6, 19), "5193430118", 31.97, 26.97, "Delivered - Mon, Jun 22",
     [("Frisco", "Multi-Cat Unscented Clumping Clay Cat Litter, 40-lb bag", "17", "99"),
      ("Inaba", "Churu Chicken Variety Lickable Cat Treats, 20 count", "13", "98")]),
    (dt.date(2026, 7, 7), "5195102271", 47.46, 40.12, "Delivered - Fri, Jul 10",
     [("Purina ONE", "Indoor Advantage Chicken Recipe Dry Cat Food, 16-lb bag", "38", "48"),
      ("Temptations", "Classic Tasty Chicken Flavor Cat Treats, 16-oz tub", "8", "98")]),
    (dt.date(2026, 7, 15), "5195866309", 42.47, 27.61, "Delivered - Sat, Jul 18",
     [("Fancy Feast", "Classic Pate Variety Pack Canned Cat Food, 3-oz can, case of 24", "24", "48"),
      ("Frisco", "Multi-Cat Unscented Clumping Clay Cat Litter, 40-lb bag", "17", "99")]),
    (dt.date(2026, 7, 29), "5197013774", 46.48, 44.16, "Delivered - Sat, Aug 1",
     [("Frisco", "Cardboard Cat Scratcher with Catnip", "11", "49"),
      ("Frontline", "Plus Flea & Tick Spot Treatment for Cats, 3 doses", "34", "99")]),
    (dt.date(2026, 8, 7), "5198126641", 45.80, 43.51, "Delivered - Mon, Aug 10",
     [("Purina ONE", "Indoor Advantage Chicken Recipe Dry Cat Food, 16-lb bag", "38", "48"),
      ("Frisco", "Multi-Cat Unscented Clumping Clay Cat Litter, 40-lb bag", "17", "99")]),
    (dt.date(2026, 8, 18), "5199044310", 24.48, 24.48, "Delivered - Fri, Aug 21",
     [("Fancy Feast", "Classic Pate Variety Pack Canned Cat Food, 3-oz can, case of 24", "24", "48")]),
    (dt.date(2026, 8, 30), "5200231855", 31.97, 30.37, "Delivered - Wed, Sep 2",
     [("Frisco", "Multi-Cat Unscented Clumping Clay Cat Litter, 40-lb bag", "17", "99"),
      ("Inaba", "Churu Chicken Variety Lickable Cat Treats, 20 count", "13", "98")]),
]

# ------------------------------------------------------------------ balance sheet
VFIFX_NAV = 66.59
STOCK_PX = {"AAPL": 231.40, "MSFT": 497.20, "COST": 918.30, "NVDA": 178.20, "VTI": 312.55,
            "SCHD": 27.15, "SOFI": 22.40, "ENPH": 34.10, "RIVN": 13.25}
STOCK_NAMES = {"AAPL": "APPLE INC", "MSFT": "MICROSOFT CORP", "COST": "COSTCO WHOLESALE CORP",
               "VFIFX": "VANGUARD TARGET RETIREMENT 2050 INVESTOR CL",
               "VMFXX": "VANGUARD FEDERAL MONEY MARKET INVESTOR CL"}
VANGUARD = {   # account number -> (balances.csv name, account_type, fund, positions [(symbol, shares)])
    "24003142": ("Vanguard Brokerage x3142", "Taxable brokerage", "VFIFX core + AAPL/MSFT/COST",
                 [("VFIFX", 612.400), ("AAPL", 80.0), ("MSFT", 21.0), ("COST", 4.0), ("VMFXX", 1204.11)]),
    "24008827": ("Vanguard Roth IRA x8827", "Roth IRA", "VFIFX + AAPL/MSFT",
                 [("VFIFX", 588.700), ("AAPL", 42.0), ("MSFT", 8.0)]),
    "24005510": ("Vanguard Rollover IRA x5510", "Rollover IRA (pre-tax)", "VFIFX Target Retirement 2050",
                 [("VFIFX", 771.902)]),
    "24000417": ("Vanguard Cash Plus x0417", "Cash Plus (bank sweep)", "Vanguard Cash Plus",
                 [("null", 9150.00)]),
}
FIDELITY_LOTS = [("NVDA", 6), ("VTI", 8), ("SCHD", 40), ("SOFI", 60), ("ENPH", 12), ("RIVN", 30)]
FIDELITY_CASH = 412.66 + 181.04
TDA_403B = 27310.44
STATE_DC = 11062.18
CU_BALANCE = 24880.35
CARD_CURRENT = {FREEDOM: 1642.18, PRIME: 894.27}
STATEMENTS = [
    {"card_id": FREEDOM, "statement_date": "2026-08-19", "statement_balance": 1127.63, "minimum_payment": 40.00, "due_date": "2026-09-16",
     "points": {"previous": 8412, "redeemed": 0, "total": 9540,
                "earn_lines": [{"label": "1% (1 Pt)/$1 earned on all purchases", "points": 1128}]}},
    {"card_id": PRIME, "statement_date": "2026-08-10", "statement_balance": 763.40, "minimum_payment": 35.00, "due_date": "2026-09-07",
     "points": {"previous": 2905, "redeemed": 0,
                "earn_lines": [{"label": "5% back on Amazon.com purchases", "points": 2064},
                               {"label": "5% back on Whole Foods Market purchases", "points": 0},
                               {"label": "2% back at gas stations", "points": 0},
                               {"label": "2% back at restaurants", "points": 0},
                               {"label": "2% back on local transit/commuting", "points": 0},
                               {"label": "1% back on all other purchases", "points": 150}]}},
]
DISCOVER_STATEMENT = {"card_id": "3160", "balance": 184.20, "as_of": "2026-08-29",
                      "subject": "Your Discover it Card statement is ready"}

# ------------------------------------------------------------------ alerts (after the card export)
ALERTS = [  # datetime, card, merchant, amount, kind
    ("2026-09-11 17:52", FREEDOM, "FOURTH STREET MARKET", 5.35, "purchase"),
    ("2026-09-11 12:18", FREEDOM, "CHIPOTLE 2291", 13.42, "purchase"),
    ("2026-09-11 08:07", PRIME, "AMAZON.COM*2K4LT9QZ0", 27.48, "purchase"),
    ("2026-09-10 19:40", FREEDOM, "TRADER JOE'S #712", 41.16, "purchase"),
    ("2026-09-10 13:05", FREEDOM, "LAKEVIEW TRANSIT AUTH", 2.75, "purchase"),
    ("2026-09-10 07:31", FREEDOM, "FOURTH STREET MARKET", 3.48, "purchase"),
    ("2026-09-09 20:14", FREEDOM, "AMC THEATRES #2255", 18.30, "purchase"),
    ("2026-09-09 18:22", FREEDOM, "CHEWY.COM", 32.15, "purchase"),
    ("2026-09-09 12:40", FREEDOM, "PANERA BREAD #601442", 11.87, "purchase"),
    ("2026-09-08 16:03", FREEDOM, "TARGET 00028215", 24.99, "credit"),
    ("2026-09-08 08:12", FREEDOM, "FOURTH STREET MARKET", 5.35, "purchase"),
    ("2026-09-07 19:55", FREEDOM, "KROGER #445", 58.21, "purchase"),
    ("2026-09-07 13:30", FREEDOM, "LYFT *RIDE SUN 1PM", 14.60, "purchase"),
    ("2026-09-07 07:44", FREEDOM, "FOURTH STREET MARKET", 3.48, "purchase"),
    ("2026-09-06 21:10", PRIME, "AMAZON PRIME*8H3TY", 14.99, "purchase"),
    ("2026-09-06 11:26", FREEDOM, "CVS/PHARMACY #8812", 16.73, "purchase"),
    ("2026-09-05 18:48", FREEDOM, "SUNFIRE TAQUERIA", 22.10, "purchase"),
    ("2026-09-05 10:02", PRIME, "AMAZON.COM*9Q1MB4TX2", 19.99, "purchase"),
    ("2026-09-04 08:15", FREEDOM, "FOURTH STREET MARKET", 5.35, "purchase"),
    ("2026-09-03 12:31", FREEDOM, "GOLDEN WOK", 15.60, "purchase"),
    ("2026-09-02 08:10", FREEDOM, "FOURTH STREET MARKET", 3.48, "purchase"),
]
ALERT_REVIEW = [{"alert_id": "1a0c44e0b2f9d3a7", "subject": "You made a $1.00 transaction with SPEEDWAY 04412",
                 "reason": "decline, reversal or authorisation hold - not settled spending",
                 "received": "2026-09-10 07:52", "card_id": FREEDOM, "from": "no.reply.alerts@chase.com"}]
