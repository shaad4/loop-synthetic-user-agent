"use client";

import { useState } from "react";

const featuredLaptop = {
  id: "aurora-14",
  name: "Aurora 14 Laptop",
  price: 64999,
  description: "14-inch laptop with 16 GB RAM, 512 GB SSD, and all-day battery life.",
};

const bundleLaptop = {
  id: "nova-13",
  name: "Nova 13 Laptop",
  price: 58999,
  description: "13-inch lightweight laptop with 16 GB RAM and a 14-hour battery.",
};

const sleevePrice = 1499;
const studentDiscount = 5000;

type CheckoutState = "cart" | "checkout" | "failed" | "success";
type BundleStage = "catalog" | "configure" | "delivery" | "review" | "failed" | "success";

export default function DemoShop() {
  const [cartCount, setCartCount] = useState(0);
  const [checkoutState, setCheckoutState] = useState<CheckoutState>("cart");
  const [errorMessage, setErrorMessage] = useState("");
  const [bundleStage, setBundleStage] = useState<BundleStage>("catalog");
  const [selectedBundleLaptop, setSelectedBundleLaptop] = useState("");
  const [includeSleeve, setIncludeSleeve] = useState(false);
  const [studentCode, setStudentCode] = useState("");
  const [discountApplied, setDiscountApplied] = useState(false);
  const [discountChecked, setDiscountChecked] = useState(false);
  const [deliveryMethod, setDeliveryMethod] = useState("Standard delivery (3–5 days)");
  const [bundleError, setBundleError] = useState("");
  const [bundleSubmitting, setBundleSubmitting] = useState(false);

  const bundleTotal = bundleLaptop.price + (includeSleeve ? sleevePrice : 0) - (discountApplied ? studentDiscount : 0);

  function addToCart() {
    setCartCount(1);
    setCheckoutState("cart");
    setErrorMessage("");
  }

  async function completePurchase() {
    const response = await fetch("/api/checkout", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ productId: featuredLaptop.id }),
    });

    if (!response.ok) {
      setCheckoutState("failed");
      setErrorMessage("We could not complete your purchase. Please try again.");
      return;
    }

    setCheckoutState("success");
  }

  function startBundle() {
    setBundleStage("configure");
    setBundleError("");
  }

  function applyStudentDiscount() {
    setDiscountChecked(true);
    setDiscountApplied(studentCode.trim().toUpperCase() === "STUDENT15");
  }

  async function placeBundleOrder() {
    setBundleSubmitting(true);
    setBundleError("");
    const response = await fetch("/api/bundle-checkout", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        laptopId: selectedBundleLaptop,
        includeSleeve,
        studentCode,
        deliveryMethod,
      }),
    });
    const payload = await response.json();
    setBundleSubmitting(false);

    if (!response.ok) {
      setBundleStage("failed");
      setBundleError(payload.error ?? "We could not validate this bundle.");
      return;
    }

    setBundleStage("success");
  }

  return (
    <main>
      <header>
        <a className="brand" href="#products">DemoShop</a>
        <p aria-live="polite">Cart: {cartCount} item{cartCount === 1 ? "" : "s"}</p>
      </header>

      <section className="hero" aria-labelledby="store-heading">
        <p className="eyebrow">STUDENT TECH STORE</p>
        <h1 id="store-heading">Find your next laptop.</h1>
        <p>Try a quick product checkout or configure a campus bundle with student pricing and delivery choices.</p>
      </section>

      <section id="products" aria-labelledby="products-heading">
        <h2 id="products-heading">Featured laptop</h2>
        <article className="product-card">
          <div className="laptop-illustration" aria-hidden="true">▱</div>
          <div>
            <h3>{featuredLaptop.name}</h3>
            <p>{featuredLaptop.description}</p>
            <p className="price">₹{featuredLaptop.price.toLocaleString("en-IN")}</p>
            <button type="button" onClick={addToCart}>Add Aurora 14 Laptop to cart</button>
          </div>
        </article>
      </section>

      <section className="bundle-intro" aria-labelledby="bundle-heading">
        <div>
          <p className="eyebrow">MULTI-STEP DEMO</p>
          <h2 id="bundle-heading">Build a campus bundle</h2>
          <p>Choose the Nova 13, add the Carry Sleeve, apply code <strong>STUDENT15</strong>, and select a delivery method.</p>
        </div>
        <button type="button" onClick={startBundle}>Build a campus bundle</button>
      </section>

      {cartCount > 0 && checkoutState === "cart" && (
        <section className="checkout-card" aria-labelledby="cart-heading">
          <h2 id="cart-heading">Your cart</h2>
          <p>{featuredLaptop.name} — ₹{featuredLaptop.price.toLocaleString("en-IN")}</p>
          <button type="button" onClick={() => setCheckoutState("checkout")}>Proceed to checkout</button>
        </section>
      )}

      {checkoutState === "checkout" && (
        <section className="checkout-card" aria-labelledby="checkout-heading">
          <h2 id="checkout-heading">Checkout</h2>
          <p>Order total: ₹{featuredLaptop.price.toLocaleString("en-IN")}</p>
          <label htmlFor="email">Email address</label>
          <input id="email" name="email" type="email" placeholder="you@example.com" />
          <button type="button" onClick={completePurchase}>Complete Purchase</button>
        </section>
      )}

      {checkoutState === "failed" && (
        <section className="checkout-card" aria-labelledby="checkout-error-heading">
          <h2 id="checkout-error-heading">Checkout unavailable</h2>
          <p className="error" role="alert">{errorMessage}</p>
          <button type="button" onClick={() => setCheckoutState("checkout")}>Try checkout again</button>
        </section>
      )}

      {checkoutState === "success" && (
        <section className="checkout-card success" aria-labelledby="confirmation-heading">
          <h2 id="confirmation-heading">Purchase complete</h2>
          <p>Your Aurora 14 Laptop order has been confirmed.</p>
        </section>
      )}

      {bundleStage === "configure" && (
        <section className="bundle-card" aria-labelledby="configure-bundle-heading">
          <p className="eyebrow">STEP 1 OF 3</p>
          <h2 id="configure-bundle-heading">Configure your campus bundle</h2>
          <fieldset>
            <legend>Choose a laptop</legend>
            <label className="choice"><input type="radio" name="bundle-laptop" value={bundleLaptop.id} checked={selectedBundleLaptop === bundleLaptop.id} onChange={(event) => setSelectedBundleLaptop(event.target.value)} />{bundleLaptop.name} — ₹{bundleLaptop.price.toLocaleString("en-IN")}</label>
          </fieldset>
          <label className="choice"><input type="checkbox" checked={includeSleeve} onChange={(event) => setIncludeSleeve(event.target.checked)} />Add Carry Sleeve — ₹{sleevePrice.toLocaleString("en-IN")}</label>
          <label htmlFor="student-code">Student discount code</label>
          <div className="inline-control"><input id="student-code" name="student-code" value={studentCode} onChange={(event) => { setStudentCode(event.target.value); setDiscountApplied(false); setDiscountChecked(false); }} placeholder="STUDENT15" /><button type="button" onClick={applyStudentDiscount}>Apply student discount</button></div>
          {discountApplied && <p className="success-note" role="status">Student discount applied — ₹{studentDiscount.toLocaleString("en-IN")} saved.</p>}
          {discountChecked && !discountApplied && <p className="error" role="alert">That student code is not recognised.</p>}
          <button type="button" disabled={selectedBundleLaptop !== bundleLaptop.id || !includeSleeve || !discountApplied} onClick={() => setBundleStage("delivery")}>Continue to delivery</button>
        </section>
      )}

      {bundleStage === "delivery" && (
        <section className="bundle-card" aria-labelledby="delivery-heading">
          <p className="eyebrow">STEP 2 OF 3</p>
          <h2 id="delivery-heading">Choose delivery</h2>
          <label htmlFor="delivery-method">Delivery method</label>
          <select id="delivery-method" name="delivery-method" value={deliveryMethod} onChange={(event) => setDeliveryMethod(event.target.value)}>
            <option>Standard delivery (3–5 days)</option>
            <option>Express delivery (next day)</option>
          </select>
          <p>Bundle total: <strong>₹{bundleTotal.toLocaleString("en-IN")}</strong></p>
          <button type="button" onClick={() => setBundleStage("review")}>Continue to review</button>
        </section>
      )}

      {bundleStage === "review" && (
        <section className="bundle-card" aria-labelledby="bundle-review-heading">
          <p className="eyebrow">STEP 3 OF 3</p>
          <h2 id="bundle-review-heading">Review your bundle</h2>
          <dl className="order-summary">
            <div><dt>Laptop</dt><dd>{bundleLaptop.name}</dd></div>
            <div><dt>Accessory</dt><dd>Carry Sleeve</dd></div>
            <div><dt>Discount</dt><dd>STUDENT15 — ₹{studentDiscount.toLocaleString("en-IN")}</dd></div>
            <div><dt>Delivery</dt><dd>{deliveryMethod}</dd></div>
            <div><dt>Total</dt><dd>₹{bundleTotal.toLocaleString("en-IN")}</dd></div>
          </dl>
          <button type="button" onClick={placeBundleOrder} disabled={bundleSubmitting}>{bundleSubmitting ? "Submitting bundle…" : "Place bundle order"}</button>
        </section>
      )}

      {bundleStage === "failed" && (
        <section className="bundle-card failure-card" aria-labelledby="bundle-error-heading">
          <h2 id="bundle-error-heading">Bundle validation failed</h2>
          <p className="error" role="alert">{bundleError}</p>
          <button type="button" onClick={() => setBundleStage("delivery")}>Return to delivery options</button>
        </section>
      )}

      {bundleStage === "success" && (
        <section className="bundle-card success" aria-labelledby="bundle-success-heading">
          <h2 id="bundle-success-heading">Campus bundle confirmed</h2>
          <p>Your Nova 13 Laptop bundle is on its way.</p>
        </section>
      )}
    </main>
  );
}
