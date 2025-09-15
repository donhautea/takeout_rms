import os
from datetime import datetime, date
import pandas as pd
import streamlit as st

from modules import db
from modules.utils import compute_profit_metrics, compute_vat, peso, ymd
from modules import invoice as inv
from modules import auth  # NEW

from modules import gdrive

st.set_page_config(page_title="TakeOut Restaurant Management System", layout="wide")

# Init DB (+ ensure admin)
db.init_db()

# --- Auth helpers ---
ROLE_LEVEL = auth.ROLE_LEVEL
PAGES = [
    "Dashboard",
    "Products & Pricing",
    "Inventory",
    "Sales & Invoicing",
    "Expenses",
    "Supplies",
    "Sales Reports",
    "Expense Reports",
    "Targets",
    "Financial Statements",
    "Shareholders",
    "Profile",
    "Admin / Users",
    "Settings / Import",
]
REQUIRES = {
    "Dashboard": "viewer",
    "Products & Pricing": "user",
    "Inventory": "user",
    "Sales & Invoicing": "user",
    "Expenses": "user",
    "Supplies": "user",
    "Sales Reports": "viewer",
    "Expense Reports": "viewer",
    "Targets": "user",
    "Financial Statements": "viewer",
    "Shareholders": "user",
    "Profile": "viewer",
    "Admin / Users": "admin",
    "Settings / Import": "user",
}

def current_user():
    return st.session_state.get("auth_user")

def require_role(page: str):
    u = current_user()
    need = REQUIRES.get(page, "viewer")
    if u is None:
        return False, f"Login required: {page} needs role **{need}**."
    if ROLE_LEVEL[u["role"]] < ROLE_LEVEL[need]:
        return False, f"Access denied: {page} needs role **{need}**, you are **{u['role']}**."
    if not u.get("is_active", True):
        return False, "Your account is inactive. Contact admin."
    return True, ""

def login_block():
    st.title("🔐 Login")
    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Login")
    if submitted:
        row = auth.get_user(username)
        if row and auth.verify_password(password, row["pw_hash"], row["pw_salt"]) and row["is_active"] == 1:
            st.session_state["auth_user"] = {
                "username": row["username"],
                "role": row["role"],
                "is_active": bool(row["is_active"]),
            }
            st.success("Welcome back!")
            st.rerun()
        else:
            st.error("Invalid credentials or inactive account.")

    st.markdown("---")
    st.subheader("📝 Register (requires admin approval)")
    with st.form("register_form"):
        r_user = st.text_input("Desired Username")
        r_pass = st.text_input("Desired Password", type="password")
        r_role = st.selectbox("Requested Role", options=["viewer", "user"])
        r_submit = st.form_submit_button("Submit Registration")
    if r_submit:
        if not r_user or not r_pass:
            st.error("Username and password are required.")
        elif auth.get_user(r_user):
            st.error("Username already exists.")
        else:
            try:
                auth.register_request(r_user, r_pass, r_role)
                st.success("Registration submitted. Waiting for admin approval.")
            except Exception as e:
                st.error(f"Registration failed: {e}")

def product_options():
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT id, name, item_code FROM products WHERE status!='Archived' ORDER BY name"
        ).fetchall()
        return {f"{r['name']} ({r['item_code'] or '—'})": r["id"] for r in rows}

# --- Sidebar ---
st.sidebar.title("🍳 TakeOut RMS")

user = current_user()
if user:
    st.sidebar.success(f"Logged in as **{user['username']}** ({user['role']})")
    if st.sidebar.button("Logout"):
        st.session_state.pop("auth_user", None)
        st.rerun()
else:
    st.sidebar.info("Not logged in")

# Navigation (show based on role)
allowed_pages = [p for p in PAGES if (user and ROLE_LEVEL[user["role"]] >= ROLE_LEVEL[REQUIRES[p]]) or p in ["Dashboard","Sales Reports","Expense Reports","Financial Statements","Profile"]]
page = st.sidebar.radio("Go to", allowed_pages, index=0)

# If not logged and page needs auth, show login/registration instead
ok, msg = require_role(page)
if not ok:
    st.warning(msg)
    login_block()          # show the login/register UI
    st.stop()              # ✅ halt the rest of the script this run


# -------------------- Dashboard --------------------
if page == "Dashboard":
    st.title("📊 Dashboard")
    with db.get_conn() as conn:
        totals = {}
        totals["products"] = conn.execute("SELECT COUNT(*) c FROM products").fetchone()["c"]
        totals["inventory_value"] = conn.execute(
            "SELECT SUM(current_inventory_value) s FROM inventory"
        ).fetchone()["s"] or 0.0
        totals["sales_all_time"] = conn.execute(
            "SELECT SUM(total_amount) s FROM sales"
        ).fetchone()["s"] or 0.0
        totals["expenses_all_time"] = conn.execute(
            "SELECT SUM(total_cost) s FROM expenses"
        ).fetchone()["s"] or 0.0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Products", totals["products"])
    c2.metric("Total Inventory Value", peso(totals["inventory_value"]))
    c3.metric("All-Time Sales", peso(totals["sales_all_time"]))
    c4.metric("All-Time Expenses", peso(totals["expenses_all_time"]))

    st.markdown("---")
    st.subheader("Quick Trends")
    left, right = st.columns(2)

    with db.get_conn() as conn:
        df_sales = pd.read_sql_query(
            """
            SELECT substr(billing_date,1,10) as d, SUM(total_amount) as sales
            FROM sales
            GROUP BY substr(billing_date,1,10)
            ORDER BY d DESC
            LIMIT 30
            """,
            conn,
        ).sort_values("d")

    with left:
        st.caption("Daily Sales (last 30 entries)")
        if not df_sales.empty:
            import matplotlib.pyplot as plt
            fig = plt.figure()
            plt.plot(df_sales["d"], df_sales["sales"])
            plt.xticks(rotation=45, ha="right")
            plt.title("Daily Sales")
            plt.xlabel("Date")
            plt.ylabel("Sales")
            st.pyplot(fig, use_container_width=True)
        else:
            st.info("No sales yet.")

    with db.get_conn() as conn:
        df_exp = pd.read_sql_query(
            """
            SELECT substr(purchase_date,1,10) as d, SUM(total_cost) as expenses
            FROM expenses
            GROUP BY substr(purchase_date,1,10)
            ORDER BY d DESC
            LIMIT 30
            """,
            conn,
        ).sort_values("d")

    with right:
        st.caption("Daily Expenses (last 30 entries)")
        if not df_exp.empty:
            import matplotlib.pyplot as plt
            fig2 = plt.figure()
            plt.plot(df_exp["d"], df_exp["expenses"])
            plt.xticks(rotation=45, ha="right")
            plt.title("Daily Expenses")
            plt.xlabel("Date")
            plt.ylabel("Expenses")
            st.pyplot(fig2, use_container_width=True)
        else:
            st.info("No expenses yet.")

# -------------------- Products & Pricing --------------------
if page == "Products & Pricing":
    st.title("🧾 Products & Pricing")
    st.caption("Create and manage products/services with cost build-up and profit analytics.")

    with db.get_conn() as conn:
        with st.form("add_product"):
            st.subheader("Add / Update Product")
            c1, c2 = st.columns([2, 1])
            with c1:
                name = st.text_input("Product/Service Name", key="p_name")
                item_code = st.text_input("Item Code (SKU)", key="p_code")
                discount = st.number_input("Discount", min_value=0.0, step=0.01)
                item_cost = st.number_input("Item Cost", min_value=0.0, step=0.01)
                tax_amount = st.number_input("Tax Amount", min_value=0.0, step=0.01)
                other_costs = st.number_input("Other Costs", min_value=0.0, step=0.01)
                selling_price = st.number_input("Item Selling Price", min_value=0.0, step=0.01)
            with c2:
                m = compute_profit_metrics(item_cost, tax_amount, other_costs, selling_price)
                st.metric("Total Cost", peso(m["total_cost"]))
                st.metric("Estimated Profit", peso(m["est_profit"]))
                st.metric("Profit Margin", f"{m['profit_margin']*100:.2f}%")

            notes = st.text_area("Notes", "")
            pid_to_update = st.selectbox(
                "Update Existing (optional)",
                options=[None] + [r["id"] for r in conn.execute("SELECT id FROM products").fetchall()],
            )

            submitted = st.form_submit_button("Save Product")
            if submitted:
                if pid_to_update:
                    conn.execute(
                        """
                        UPDATE products
                           SET name=?, item_code=?, discount=?, item_cost=?, tax_amount=?, other_costs=?,
                               total_cost=?, selling_price=?, est_profit=?, profit_margin=?, notes=?
                         WHERE id=?
                        """,
                        (
                            name, item_code, discount, item_cost, tax_amount, other_costs,
                            m["total_cost"], selling_price, m["est_profit"], m["profit_margin"],
                            notes, pid_to_update,
                        ),
                    )
                    st.success("Product updated.")
                else:
                    conn.execute(
                        """
                        INSERT INTO products
                          (name, item_code, discount, item_cost, tax_amount, other_costs,
                           total_cost, selling_price, est_profit, profit_margin, notes)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            name, item_code, discount, item_cost, tax_amount, other_costs,
                            m["total_cost"], selling_price, m["est_profit"], m["profit_margin"],
                            notes,
                        ),
                    )
                    st.success("Product added.")

        st.markdown("---")
        df = pd.read_sql_query("SELECT * FROM products ORDER BY name", conn)
        st.dataframe(df, use_container_width=True)

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Average Cost", peso(df["total_cost"].mean() if not df.empty else 0))
        c2.metric("Average Item Price", peso(df["selling_price"].mean() if not df.empty else 0))
        c3.metric("Average Gross Profit", peso(df["est_profit"].mean() if not df.empty else 0))
        c4.metric("Average Profit Margin", f"{(df['profit_margin'].mean()*100) if not df.empty else 0:.2f}%")

        if not df.empty:
            del_id = st.selectbox("Delete Product ID", options=[None] + df["id"].tolist())
            if st.button("Delete Selected Product") and del_id:
                conn.execute("DELETE FROM products WHERE id=?", (int(del_id),))
                st.warning("Product deleted. Refresh to see changes.")

# -------------------- Inventory --------------------
if page == "Inventory":
    st.title("📦 Inventory")
    st.caption("Stock-in logs and current inventory status.")
    with db.get_conn() as conn:
        opts = product_options()
        with st.form("stock_in_form"):
            st.subheader("Stock In")
            pid_label = st.selectbox("Product", options=list(opts.keys()))
            qty = st.number_input("Stocks Added", min_value=1, step=1)
            status = st.selectbox("Status", options=["Stock In", "Adjustment"])
            notes = st.text_input("Notes", "")
            submitted = st.form_submit_button("Add Stock")
            if submitted:
                product_id = opts[pid_label]
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                conn.execute(
                    "INSERT INTO stock_in_logs (stock_in_ts, product_id, stocks_added, status, notes) VALUES (?,?,?,?,?)",
                    (ts, product_id, int(qty), status, notes),
                )
                row = conn.execute("SELECT * FROM inventory WHERE product_id=?", (product_id,)).fetchone()
                price = conn.execute("SELECT selling_price FROM products WHERE id=?", (product_id,)).fetchone()["selling_price"] or 0.0
                if row:
                    new_avail = (row["available_stock"] or 0) + int(qty)
                    conn.execute(
                        """
                        UPDATE inventory
                           SET available_stock=?,
                               all_time_stock_in=COALESCE(all_time_stock_in,0)+?,
                               current_inventory_value=?
                         WHERE product_id=?
                        """,
                        (new_avail, int(qty), new_avail * price, product_id),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO inventory (product_id, available_stock, low_stock_alert, status, current_inventory_value, all_time_stock_in, all_time_stock_out, all_time_sales)
                        VALUES (?,?,?,?,?,?,?,?)
                        """,
                        (product_id, int(qty), 0, "In Stock", int(qty) * price, int(qty), 0, 0.0),
                    )
                st.success("Stock in recorded.")

        st.markdown("---")
        st.subheader("Stock-in Logs")
        logs = pd.read_sql_query(
            """
            SELECT l.id, l.stock_in_ts as "Stock In DateTime", p.name as "Product Name",
                   l.stocks_added as "Stocks Added", l.status as "Status", l.notes as "Notes"
              FROM stock_in_logs l
              JOIN products p ON p.id = l.product_id
             ORDER BY l.stock_in_ts DESC
            """,
            conn,
        )
        st.dataframe(logs, use_container_width=True)

        st.subheader("Inventory Status")
        inv_df = pd.read_sql_query(
            """
            SELECT i.id, p.name as "Product Name", p.selling_price as "Item Price",
                   i.available_stock as "Available Stock", i.low_stock_alert as "Low Stock Alert",
                   i.status as "Status", i.current_inventory_value as "Current Inventory Value",
                   i.all_time_stock_in as "All Time Stock In", i.all_time_stock_out as "All Time Stock Out",
                   i.all_time_sales as "All Time Sales"
              FROM inventory i
              JOIN products p ON p.id = i.product_id
              ORDER BY p.name
            """,
            conn,
        )
        st.dataframe(inv_df, use_container_width=True)

        total_val = inv_df["Current Inventory Value"].sum() if not inv_df.empty else 0.0
        st.metric("Total Inventory Value", peso(total_val))

        if not inv_df.empty:
            in_stock = (inv_df["Available Stock"] > 0).sum()
            low_stock = (inv_df["Available Stock"] <= inv_df["Low Stock Alert"]).sum()
            out_of_stock = (inv_df["Available Stock"] <= 0).sum()
            c1, c2, c3 = st.columns(3)
            c1.metric("In Stock", in_stock)
            c2.metric("Low Stock", low_stock)
            c3.metric("Out of Stock", out_of_stock)

# -------------------- Sales & Invoicing --------------------
if page == "Sales & Invoicing":
    st.title("🧾 Sales & Invoicing")
    with db.get_conn() as conn:
        opts = product_options()
        with st.form("sales_form"):
            st.subheader("Record Sale")
            billing_date = st.date_input("Billing Date", value=date.today())
            pid_label = st.selectbox("Product", options=list(opts.keys()))
            qty = st.number_input("Quantity", min_value=1, step=1)
            item_price = st.number_input("Item Price", min_value=0.0, step=0.01)
            discount = st.number_input("Discount", min_value=0.0, step=0.01)
            vat_incl = st.checkbox("VAT Inclusive?", value=True)
            payment_status = st.selectbox("Payment Status", options=["Paid", "Unpaid", "Partially Paid"])
            sales_channel = st.selectbox("Sales Channel", options=["Walk-in", "Delivery", "Online", "Catering"])
            customer_name = st.text_input("Customer Name")
            customer_tin = st.text_input("TIN Number")
            business_address = st.text_input("Business Address")
            notes = st.text_area("Notes", "")
            submit = st.form_submit_button("Save Sale")

            if submit:
                product_id = opts[pid_label]
                line_total_gross = (item_price * qty) - discount
                vat_amt, net_of_vat = compute_vat(vat_incl, line_total_gross)
                conn.execute(
                    """
                    INSERT INTO sales (billing_date, product_id, quantity, item_price, discount, total_amount,
                                       payment_status, sales_channel, customer_name, customer_tin, business_address,
                                       notes, vat_inclusive, vat_amount, net_of_vat)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        ymd(billing_date),
                        product_id,
                        int(qty),
                        item_price,
                        discount,
                        line_total_gross,
                        payment_status,
                        sales_channel,
                        customer_name,
                        customer_tin,
                        business_address,
                        notes,
                        1 if vat_incl else 0,
                        vat_amt,
                        net_of_vat,
                    ),
                )
                inv_row = conn.execute("SELECT * FROM inventory WHERE product_id=?", (product_id,)).fetchone()
                price = conn.execute("SELECT selling_price FROM products WHERE id=?", (product_id,)).fetchone()["selling_price"] or 0.0
                if inv_row:
                    new_avail = (inv_row["available_stock"] or 0) - int(qty)
                    conn.execute(
                        """
                        UPDATE inventory
                           SET available_stock=?,
                               all_time_stock_out=COALESCE(all_time_stock_out,0)+?,
                               all_time_sales=COALESCE(all_time_sales,0)+?,
                               current_inventory_value=?
                         WHERE product_id=?
                        """,
                        (new_avail, int(qty), line_total_gross, max(new_avail, 0) * price, product_id),
                    )
                st.success("Sale recorded.")

    st.markdown("---")
    with db.get_conn() as conn:
        sales_df = pd.read_sql_query(
            """
            SELECT s.id, s.billing_date as "Billing Date", p.name as "Product", s.quantity as "Quantity",
                   s.item_price as "Item Price", s.discount as "Discount", s.total_amount as "Total Amount",
                   s.payment_status as "Payment Status", s.sales_channel as "Sales Channel",
                   s.customer_name as "Customer Name", s.customer_tin as "TIN Number",
                   s.business_address as "Business Address", s.notes as "Notes",
                   CASE WHEN s.vat_inclusive=1 THEN 'Yes' ELSE 'No' END as "VAT Inclusive",
                   s.vat_amount as "VAT", s.net_of_vat as "Net of VAT", s.invoice_no as "Invoice No"
              FROM sales s
              JOIN products p ON p.id = s.product_id
              ORDER BY s.billing_date DESC, s.id DESC
            """,
            conn,
        )
    st.subheader("Sales Listing")
    st.dataframe(sales_df, use_container_width=True)

    st.subheader("Invoice Generator")
    inv_id = st.selectbox("Select Sale ID for Invoice", options=[None] + sales_df["id"].tolist())
    if st.button("Generate Invoice HTML") and inv_id:
        with db.get_conn() as conn:
            row = conn.execute(
                """
                SELECT s.*, p.name as product_name
                  FROM sales s
                  JOIN products p ON p.id=s.product_id
                 WHERE s.id=?
                """,
                (int(inv_id),),
            ).fetchone()
        invoice_no = row["invoice_no"] or f"INV-{row['id']:06d}"
        if not row["invoice_no"]:
            with db.get_conn() as conn:
                conn.execute("UPDATE sales SET invoice_no=? WHERE id=?", (invoice_no, int(inv_id)))

        rows = [
            {
                "product_name": row["product_name"],
                "quantity": row["quantity"],
                "item_price": row["item_price"],
                "discount": row["discount"],
                "line_total": row["total_amount"],
            }
        ]
        subtotal = row["net_of_vat"] if row["vat_inclusive"] == 1 else (row["total_amount"])
        vat = row["vat_amount"]
        grand_total = row["total_amount"] if row["vat_inclusive"] == 1 else (row["total_amount"] + row["vat_amount"])

        html = inv.render_invoice_html(
            invoice_no=invoice_no,
            billing_date=row["billing_date"],
            customer_name=row["customer_name"],
            customer_tin=row["customer_tin"],
            business_address=row["business_address"],
            rows=rows,
            subtotal=subtotal,
            vat=vat,
            grand_total=grand_total,
        )
        out_dir = "invoices"
        os.makedirs(out_dir, exist_ok=True)
        file_path = os.path.join(out_dir, f"{invoice_no}.html")
        inv.save_invoice_html(file_path, html)
        try:
            fid = gdrive.upload_file(file_path, st.secrets["gdrive"]["folder_id"])
            st.info(f"Invoice uploaded to Drive (file id: {fid})")
        except Exception as e:
            st.warning(f"Drive upload skipped: {e}")
                
        st.success(f"Invoice generated: {file_path}")
        with open(file_path, "rb") as f:
            st.download_button("Download Invoice HTML", f, file_name=f"{invoice_no}.html", mime="text/html")

# -------------------- Expenses --------------------
if page == "Expenses":
    st.title("💸 Expenses")
    with db.get_conn() as conn:
        with st.form("expenses_form"):
            purchase_date = st.date_input("Purchase Date", value=date.today())
            category = st.text_input("Category")
            description = st.text_input("Item Description")
            total_cost = st.number_input("Total Cost", min_value=0.0, step=0.01)
            status = st.selectbox("Status", options=["Posted", "Pending", "Cancelled"])
            receipt_no = st.text_input("Receipt No")
            vendor_name = st.text_input("Vendor Name")
            vendor_tin = st.text_input("TIN No")
            business_address = st.text_input("Business Address")
            notes = st.text_area("Notes", "")
            submitted = st.form_submit_button("Save Expense")
            if submitted:
                conn.execute(
                    """
                    INSERT INTO expenses (purchase_date, category, description, total_cost, status, receipt_no, vendor_name, vendor_tin, business_address, notes)
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                    """,
                    (ymd(purchase_date), category, description, total_cost, status, receipt_no, vendor_name, vendor_tin, business_address, notes),
                )
                st.success("Expense saved.")

        st.markdown("---")
        df = pd.read_sql_query("SELECT * FROM expenses ORDER BY purchase_date DESC, id DESC", conn)
        st.dataframe(df, use_container_width=True)

# -------------------- Supplies --------------------
if page == "Supplies":
    st.title("🧰 Supplies Inventory")
    with db.get_conn() as conn:
        with st.form("supplies_form"):
            item_description = st.text_input("Item Description")
            supplier = st.text_input("Supplier")
            units_per_piece = st.number_input("Units per Piece", min_value=0.0, step=0.01, value=1.0)
            unit_symbol = st.text_input("Unit Symbol (e.g., g, ml, pcs)")
            item_cost = st.number_input("Item Cost", min_value=0.0, step=0.01)
            available_stocks = st.number_input("Available Stocks", min_value=0.0, step=0.01)
            low_stock_alert = st.number_input("Low Stock Alert Level", min_value=0.0, step=0.01, value=0.0)
            status = st.selectbox("Status", options=["In Stock", "Low Stock", "Out of Stock"])
            notes = st.text_area("Notes", "")
            submitted = st.form_submit_button("Save Supply")
            if submitted:
                conn.execute(
                    """
                    INSERT INTO supplies (item_description, supplier, units_per_piece, unit_symbol, item_cost, last_updated, available_stocks, low_stock_alert, status, inventory_value, notes)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (item_description, supplier, units_per_piece, unit_symbol, item_cost, ymd(datetime.now()), available_stocks, low_stock_alert, status, item_cost * available_stocks, notes),
                )
                st.success("Supply saved.")

        st.markdown("---")
        df = pd.read_sql_query("SELECT * FROM supplies ORDER BY item_description", conn)
        st.dataframe(df, use_container_width=True)

# -------------------- Sales Reports --------------------
if page == "Sales Reports":
    st.title("📈 Sales Reports")
    with db.get_conn() as conn:
        sales = pd.read_sql_query(
            """
            SELECT s.*, p.name as product_name
              FROM sales s
              JOIN products p ON p.id = s.product_id
            """,
            conn,
        )

    if sales.empty:
        st.info("No sales data yet.")
    else:
        st.subheader("Daily Sales Breakdown")
        daily = sales.copy()
        daily["d"] = daily["billing_date"].str.slice(0, 10)
        g_daily = daily.groupby("d", as_index=False)["total_amount"].sum()
        st.dataframe(g_daily, use_container_width=True)

        st.subheader("Monthly Sales Breakdown")
        monthly = sales.copy()
        monthly["m"] = monthly["billing_date"].str.slice(0, 7)
        g_month = monthly.groupby("m", as_index=False)["total_amount"].sum()
        st.dataframe(g_month, use_container_width=True)

        st.subheader("Top 20 Best Selling Product")
        top = (
            sales.groupby("product_name", as_index=False)
            .agg(quantity=("quantity", "sum"), sales=("total_amount", "sum"))
            .sort_values("sales", ascending=False)
            .head(20)
        )
        st.dataframe(top, use_container_width=True)

        st.subheader("Top Sales Channel")
        chan = (
            sales.groupby("sales_channel", as_index=False)["total_amount"]
            .sum()
            .sort_values("total_amount", ascending=False)
        )
        st.dataframe(chan, use_container_width=True)

        st.markdown("---")
        st.subheader("Trends")
        import matplotlib.pyplot as plt

        with db.get_conn() as conn:
            exp = pd.read_sql_query("SELECT * FROM expenses", conn)

        exp["m"] = exp["purchase_date"].str.slice(0, 7) if not exp.empty else pd.Series(dtype=str)
        g_exp_m = (
            exp.groupby("m", as_index=False)["total_cost"].sum()
            if not exp.empty
            else pd.DataFrame(columns=["m", "total_cost"])
        )

        fig1 = plt.figure()
        plt.plot(g_month["m"], g_month["total_amount"], label="Sales")
        if not g_exp_m.empty:
            m_merge = pd.merge(g_month, g_exp_m, on="m", how="left").fillna(0)
            plt.plot(m_merge["m"], m_merge["total_cost"], label="Expenses")
        plt.xticks(rotation=45, ha="right")
        plt.title("Monthly Sales vs Expenses")
        plt.xlabel("Month")
        plt.ylabel("Amount")
        plt.legend()
        st.pyplot(fig1, use_container_width=True)

        exp["d"] = exp["purchase_date"].str.slice(0, 10) if not exp.empty else pd.Series(dtype=str)
        g_exp_d = (
            exp.groupby("d", as_index=False)["total_cost"].sum()
            if not exp.empty
            else pd.DataFrame(columns=["d", "total_cost"])
        )

        fig2 = plt.figure()
        plt.plot(g_daily["d"], g_daily["total_amount"], label="Sales")
        if not g_exp_d.empty:
            d_merge = pd.merge(g_daily, g_exp_d, on="d", how="left").fillna(0)
            plt.plot(d_merge["d"], d_merge["total_cost"], label="Expenses")
        plt.xticks(rotation=45, ha="right")
        plt.title("Daily Sales vs Expenses")
        plt.xlabel("Date")
        plt.ylabel("Amount")
        plt.legend()
        st.pyplot(fig2, use_container_width=True)

# -------------------- Expense Reports --------------------
if page == "Expense Reports":
    st.title("🧮 Expense Reports")
    with db.get_conn() as conn:
        exp = pd.read_sql_query("SELECT * FROM expenses", conn)

    if exp.empty:
        st.info("No expenses yet.")
    else:
        st.metric("All-Time Expenses", peso(exp["total_cost"].sum()))
        st.subheader("Categories Breakdown")
        cats = exp.groupby("category", as_index=False)["total_cost"].sum().sort_values("total_cost", ascending=False)
        st.dataframe(cats, use_container_width=True)
        st.subheader("Daily Expense Trend")
        exp["d"] = exp["purchase_date"].str.slice(0, 10); g_d = exp.groupby("d", as_index=False)["total_cost"].sum(); st.dataframe(g_d, use_container_width=True)
        st.subheader("Monthly Expense Breakdown")
        exp["m"] = exp["purchase_date"].str.slice(0, 7); g_m = exp.groupby("m", as_index=False)["total_cost"].sum(); st.dataframe(g_m, use_container_width=True)
        st.subheader("Yearly Expense Breakdown")
        exp["y"] = exp["purchase_date"].str.slice(0, 4); g_y = exp.groupby("y", as_index=False)["total_cost"].sum(); st.dataframe(g_y, use_container_width=True)

# -------------------- Targets --------------------
if page == "Targets":
    st.title("🎯 Target Goals")
    with db.get_conn() as conn:
        with st.form("targets_form"):
            period = st.text_input("Period (YYYY-MM)", value=datetime.now().strftime("%Y-%m"))
            sales_target = st.number_input("Sales Target", min_value=0.0, step=0.01)
            expense_target = st.number_input("Expense Target", min_value=0.0, step=0.01)
            profit_target = st.number_input("Profit Target", min_value=0.0, step=0.01)
            notes = st.text_area("Notes", "")
            submitted = st.form_submit_button("Save Target")
            if submitted:
                conn.execute(
                    "INSERT INTO targets (period, sales_target, expense_target, profit_target, notes) VALUES (?,?,?,?,?)",
                    (period, sales_target, expense_target, profit_target, notes),
                )
                st.success("Target saved.")

    st.markdown("---")
    with db.get_conn() as conn:
        df = pd.read_sql_query("SELECT * FROM targets ORDER BY period DESC", conn)
    st.dataframe(df, use_container_width=True)

# -------------------- Financial Statements --------------------
if page == "Financial Statements":
    st.title("📒 Financial Statements")
    with db.get_conn() as conn:
        sales = pd.read_sql_query("SELECT * FROM sales", conn)
        exp = pd.read_sql_query("SELECT * FROM expenses", conn)

    rev = sales["total_amount"].sum() if not sales.empty else 0.0
    vat_collected = sales["vat_amount"].sum() if not sales.empty else 0.0
    net_sales = sales["net_of_vat"].sum() if not sales.empty else 0.0
    cogs = 0.0
    gross_profit = net_sales - cogs
    opex = exp["total_cost"].sum() if not exp.empty else 0.0
    operating_income = gross_profit - opex
    cash_inflows = rev
    cash_outflows = opex
    net_cash_flow = cash_inflows - cash_outflows

    st.subheader("Income Statement (P&L)")
    st.write(pd.DataFrame({
        "Metric": ["Gross Sales", "VAT Collected", "Net Sales", "COGS (placeholder)", "Gross Profit", "Operating Expenses", "Operating Income"],
        "Amount": [rev, vat_collected, net_sales, cogs, gross_profit, opex, operating_income],
    }))

    st.subheader("Cash Flow Statement (Simplified)")
    st.write(pd.DataFrame({
        "Metric": ["Cash Inflows (Sales)", "Cash Outflows (Expenses)", "Net Cash Flow"],
        "Amount": [cash_inflows, cash_outflows, net_cash_flow],
    }))

# -------------------- Shareholders --------------------
if page == "Shareholders":
    st.title("🧑‍🤝‍🧑 Shareholders")
    with db.get_conn() as conn:
        with st.form("shareholder_form"):
            name = st.text_input("Name")
            pct = st.number_input("Ownership %", min_value=0.0, max_value=100.0, step=0.01)
            notes = st.text_area("Notes", "")
            submitted = st.form_submit_button("Save Shareholder")
            if submitted:
                conn.execute("INSERT INTO shareholders (name, ownership_pct, notes) VALUES (?,?,?)", (name, pct, notes))
                st.success("Shareholder saved.")

    st.markdown("---")
    with db.get_conn() as conn:
        df = pd.read_sql_query("SELECT * FROM shareholders ORDER BY ownership_pct DESC", conn)
    st.dataframe(df, use_container_width=True)

# -------------------- Profile (password change request) --------------------
if page == "Profile":
    st.title("👤 Profile")
    u = current_user()
    st.info(f"Logged in as **{u['username']}** (role: **{u['role']}**)")

    st.subheader("Change Password (requires admin approval)")
    with st.form("pw_change"):
        new_pw = st.text_input("New Password", type="password")
        new_pw2 = st.text_input("Confirm New Password", type="password")
        sub = st.form_submit_button("Submit Change Request")
    if sub:
        if not new_pw or new_pw != new_pw2:
            st.error("Passwords do not match.")
        else:
            try:
                auth.request_password_change(u["username"], new_pw)
                st.success("Password change requested. Wait for admin approval.")
            except Exception as e:
                st.error(f"Request failed: {e}")

# -------------------- Admin / Users --------------------
if page == "Admin / Users":
    st.title("🛡️ Admin / Users")
    st.caption("Approve registrations, approve/deny password changes, manage roles & activation.")

    st.subheader("Pending Registrations")
    pend = auth.list_pending_users()
    if not pend:
        st.success("No pending registrations.")
    else:
        for p in pend:
            c1, c2, c3, c4, c5 = st.columns([2, 2, 2, 2, 2])
            c1.write(f"**{p['username']}**")
            role_sel = c2.selectbox(f"Role for {p['username']}", ["viewer", "user", "admin"], key=f"role_{p['id']}")
            if c3.button("Approve", key=f"app_{p['id']}"):
                ok = auth.approve_user(p["id"], role_sel)
                if ok:
                    st.success(f"Approved {p['username']} as {role_sel}.")
                    st.rerun()
            if c4.button("Deny", key=f"deny_{p['id']}"):
                auth.deny_user(p["id"])
                st.warning(f"Denied {p['username']}.")
                st.rerun()
            c5.write(p["created_at"])

    st.markdown("---")
    st.subheader("Pending Password Changes")
    pwreqs = auth.list_password_requests()
    if not pwreqs:
        st.success("No pending password change requests.")
    else:
        for r in pwreqs:
            c1, c2, c3 = st.columns([3, 1, 1])
            c1.write(f"**{r['username']}** requested on {r['created_at']}")
            if c2.button("Approve", key=f"apppw_{r['id']}"):
                ok = auth.approve_password_change(r["id"])
                if ok:
                    st.success(f"Password updated for {r['username']}.")
                    st.rerun()
            if c3.button("Deny", key=f"denypw_{r['id']}"):
                auth.deny_password_change(r["id"])
                st.warning(f"Password change denied for {r['username']}.")
                st.rerun()

    st.markdown("---")
    st.subheader("All Users")
    users = auth.list_users()
    for u in users:
        c1, c2, c3, c4, c5 = st.columns([2, 2, 2, 2, 2])
        c1.write(f"**{u['username']}**")
        role_new = c2.selectbox(f"Role for {u['username']}", ["guest","viewer","user","admin"], index=["guest","viewer","user","admin"].index(u["role"]), key=f"roleuser_{u['id']}")
        active_new = c3.checkbox("Active", value=bool(u["is_active"]), key=f"active_{u['id']}")
        if c4.button("Update", key=f"upd_{u['id']}"):
            auth.set_user_role(u["id"], role_new)
            auth.set_user_active(u["id"], active_new)
            st.success(f"Updated {u['username']} → role={role_new}, active={active_new}")
            st.rerun()
        c5.write(u["created_at"])

# -------------------- Settings / Import --------------------
if page == "Settings / Import":
    st.title("⚙️ Settings / Import")
    st.caption("Import products & inventory from Excel with column mapping; download DB.")

    uploaded = st.file_uploader("Upload Excel (.xlsx)", type=["xlsx"])
    if uploaded is not None:
        try:
            xls = pd.ExcelFile(uploaded)
            sheet = st.selectbox("Select sheet", xls.sheet_names)
            df_raw = xls.parse(sheet)

            st.write("**Preview (first 50 rows):**")
            st.dataframe(df_raw.head(50), use_container_width=True)

            st.write("#### Map Columns")
            cols = df_raw.columns.tolist()

            def pick(label):
                return st.selectbox(label, [None] + cols)

            map_name = pick("Product/Service Name")
            map_code = pick("Item Code (SKU)")
            map_price = pick("Item Selling Price")
            map_disc = pick("Discount")
            map_cost = pick("Item Cost")
            map_tax = pick("Tax Amount")
            map_other = pick("Other Costs")
            map_avail = pick("Available Stock")
            map_low = pick("Low Stock Alert Level")
            map_notes = pick("Notes (optional)")

            upsert = st.checkbox("Upsert by Item Code", value=True)
            recalc = st.checkbox("Recompute cost/profit/margin", value=True)
            clear_all = st.checkbox("Danger: Clear ALL products & inventory first", value=False)

            if st.button("Run Import"):
                with db.get_conn() as conn:
                    cur = conn.cursor()

                    if clear_all:
                        cur.execute("DELETE FROM stock_in_logs")
                        cur.execute("DELETE FROM inventory")
                        cur.execute("DELETE FROM products")
                        conn.commit()

                    ins = 0
                    upd = 0

                    for _, r in df_raw.iterrows():
                        name = str(r.get(map_name, "") or "").strip() if map_name else ""
                        code = str(r.get(map_code, "") or "").strip() if map_code else ""
                        if not name or not code:
                            continue

                        price = float(r.get(map_price, 0) or 0) if map_price else 0.0
                        disc = float(r.get(map_disc, 0) or 0) if map_disc else 0.0
                        cost = float(r.get(map_cost, 0) or 0) if map_cost else 0.0
                        tax = float(r.get(map_tax, 0) or 0) if map_tax else 0.0
                        other = float(r.get(map_other, 0) or 0) if map_other else 0.0
                        avail = int(float(r.get(map_avail, 0) or 0)) if map_avail else 0
                        low = int(float(r.get(map_low, 0) or 0)) if map_low else 0
                        notes = str(r.get(map_notes, "") or "") if map_notes else ""

                        if recalc:
                            m = compute_profit_metrics(cost, tax, other, price)
                            total_cost = m["total_cost"]
                            est_profit = m["est_profit"]
                            margin = m["profit_margin"]
                        else:
                            total_cost = cost + tax + other
                            est_profit = price - total_cost
                            margin = (est_profit / price) if price else 0.0

                        existing = cur.execute("SELECT id FROM products WHERE item_code=?", (code,)).fetchone()
                        if existing and upsert:
                            pid = existing["id"]
                            cur.execute(
                                """
                                UPDATE products SET
                                  name=?, discount=?, item_cost=?, tax_amount=?, other_costs=?,
                                  total_cost=?, selling_price=?, est_profit=?, profit_margin=?, notes=?
                                WHERE id=?
                                """,
                                (name, disc, cost, tax, other, total_cost, price, est_profit, margin, notes, pid),
                            )
                            upd += 1
                        else:
                            cur.execute(
                                """
                                INSERT INTO products (name, item_code, discount, item_cost, tax_amount, other_costs,
                                                      total_cost, selling_price, est_profit, profit_margin, notes)
                                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                                """,
                                (name, code, disc, cost, tax, other, total_cost, price, est_profit, margin, notes),
                            )
                            pid = cur.lastrowid
                            ins += 1

                        inv = cur.execute("SELECT * FROM inventory WHERE product_id=?", (pid,)).fetchone()
                        inv_val = max(avail, 0) * price
                        status = "In Stock" if avail > 0 else "Out of Stock"
                        if inv:
                            cur.execute(
                                "UPDATE inventory SET available_stock=?, low_stock_alert=?, status=?, current_inventory_value=? WHERE product_id=?",
                                (avail, low, status, inv_val, pid),
                            )
                        else:
                            cur.execute(
                                """
                                INSERT INTO inventory (product_id, available_stock, low_stock_alert, status,
                                                       current_inventory_value, all_time_stock_in, all_time_stock_out, all_time_sales)
                                VALUES (?,?,?,?,?,?,?,?)
                                """,
                                (pid, avail, low, status, inv_val, avail, 0, 0.0),
                            )

                    conn.commit()
                st.success(f"Import complete. Inserted: {ins}, Updated: {upd}")

        except Exception as e:
            st.error(f"Import failed: {e}")

    st.markdown("---")
    st.caption("Database download / reset")
    db_file = os.environ.get("TAKEOUT_DB_PATH", "takeout.db")
    if os.path.exists(db_file):
        with open(db_file, "rb") as f:
            st.download_button(
                "Download Database (SQLite)",
                f,
                file_name=os.path.basename(db_file),
                mime="application/octet-stream",
            )
    st.markdown("> Tip: Back up your DB before importing. You can reset by deleting `takeout.db` and restarting the app.")

    st.markdown("## ☁️ Google Drive Backup / Restore")

folder_id = st.secrets["gdrive"]["folder_id"]
db_file = os.environ.get("TAKEOUT_DB_PATH", "takeout.db")

c1, c2 = st.columns(2)
with c1:
    if st.button("Backup SQLite DB → Google Drive"):
        try:
            fid = gdrive.upload_file(db_file, folder_id)
            st.success(f"DB uploaded to Drive (file id: {fid})")
        except Exception as e:
            st.error(f"Backup failed: {e}")

with c2:
    st.caption("List files in Drive folder")
    try:
        files = gdrive.list_files(folder_id)
        import pandas as pd
        st.dataframe(pd.DataFrame(files), use_container_width=True)
    except Exception as e:
        st.error(f"List failed: {e}")

st.markdown("### Restore DB from Drive")
try:
    files = gdrive.list_files(folder_id)
    db_candidates = [f for f in files if f["name"].endswith(".db")]
    restore_label = st.selectbox(
        "Pick a .db file from Drive to restore",
        options=[f'{f["name"]}  ({f["id"]})' for f in db_candidates] or ["— none —"],
    )
    if restore_label != "— none —":
        chosen = db_candidates[[f'{f["name"]}  ({f["id"]})' for f in db_candidates].index(restore_label)]
        if st.button("Restore selected DB"):
            tmp_path = os.path.join("tmp_restore.db")
            gdrive.download_file(chosen["id"], tmp_path)
            # Safety: move current DB aside, then replace
            backup_local = db_file + ".pre-restore.bak"
            try:
                if os.path.exists(db_file):
                    os.replace(db_file, backup_local)
                os.replace(tmp_path, db_file)
                st.success("Restore complete. Please restart the app.")
            except Exception as e:
                st.error(f"Restore failed: {e}")
except Exception as e:
    st.error(f"Restore UI error: {e}")

