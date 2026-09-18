import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { PricingCards } from "./PricingCards";

describe("PricingCards", () => {
  const plans = [
    {
      id: "nitya",
      name: "AYANA Nitya",
      tagline: "Basic plan",
      price: { USD: { month: 9.99, year: 99.90 }, INR: { month: 949, year: 9490 } },
      features: ["Feature 1", "Feature 2"],
    },
    {
      id: "bandham",
      name: "AYANA Bandham",
      tagline: "Premium plan",
      highlight: true,
      price: { USD: { month: 19.99, year: 199.90 }, INR: { month: 1799, year: 17990 } },
      features: ["Feature 1", "Feature 2", "Feature 3"],
    },
  ];
  
  const currencies = [
    { code: "USD", symbol: "$", label: "USD" },
    { code: "INR", symbol: "₹", label: "INR" },
  ];

  it("renders plans with default USD/Monthly billing", () => {
    render(<PricingCards plans={plans} currencies={currencies} />);
    
    expect(screen.getByText("AYANA Nitya")).toBeInTheDocument();
    expect(screen.getByText("AYANA Bandham")).toBeInTheDocument();
    expect(screen.getByText("Most loved")).toBeInTheDocument();
    
    // Check initial price display (USD, month)
    expect(screen.getByText("$9.99")).toBeInTheDocument();
    expect(screen.getByText("$19.99")).toBeInTheDocument();
  });

  it("toggles billing cycle to yearly", () => {
    render(<PricingCards plans={plans} currencies={currencies} />);
    
    const yearlyBtn = screen.getByTestId("billing-year");
    fireEvent.click(yearlyBtn);
    
    // Annual view shows per-month equivalent (yearCents / 12 / 100)
    // Nitya: 99.90 * 100 = 9990 cents / 12 = 832.5 → round → 833 / 100 = 8.33
    // Bandham: 199.90 * 100 = 19990 cents / 12 = 1665.8 → round → 1666 / 100 = 16.66
    expect(screen.getByText("$8.33")).toBeInTheDocument();
    expect(screen.getByText("$16.66")).toBeInTheDocument();
  });

  it("changes currency via select", () => {
    render(<PricingCards plans={plans} currencies={currencies} />);
    
    const currencySelect = screen.getByTestId("currency-select");
    fireEvent.change(currencySelect, { target: { value: "INR" } });
    
    // Check updated price display (INR, month)
    expect(screen.getByText("₹949")).toBeInTheDocument();
    expect(screen.getByText("₹1799")).toBeInTheDocument();
  });

  it("calls onSelect when a plan is chosen", () => {
    const onSelectMock = jest.fn();
    render(<PricingCards plans={plans} currencies={currencies} onSelect={onSelectMock} />);
    
    const selectNitya = screen.getByTestId("select-plan-nitya");
    fireEvent.click(selectNitya);
    
    expect(onSelectMock).toHaveBeenCalledWith("nitya", "month", "USD");
  });

  it("shows selected state for the active plan", () => {
    render(<PricingCards plans={plans} currencies={currencies} selectedPlan="nitya" onSelect={jest.fn()} />);
    
    const selectNitya = screen.getByTestId("select-plan-nitya");
    expect(selectNitya).toHaveTextContent("Selected ✓");
  });
});
