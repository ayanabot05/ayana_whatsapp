import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { PricingCards } from "./PricingCards";

describe("PricingCards", () => {
  const plans = [
    {
      id: "nitya",
      name: "AYANA Nitya",
      tagline: "Basic plan",
      price: { USD: { month: 10, year: 100 }, INR: { month: 800, year: 8000 } },
      features: ["Feature 1", "Feature 2"],
    },
    {
      id: "bandham",
      name: "AYANA Bandham",
      tagline: "Premium plan",
      highlight: true,
      price: { USD: { month: 20, year: 200 }, INR: { month: 1600, year: 16000 } },
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
    expect(screen.getByText("$10")).toBeInTheDocument();
    expect(screen.getByText("$20")).toBeInTheDocument();
  });

  it("toggles billing cycle to yearly", () => {
    render(<PricingCards plans={plans} currencies={currencies} />);
    
    const yearlyBtn = screen.getByTestId("billing-year");
    fireEvent.click(yearlyBtn);
    
    // Check updated price display (USD, year)
    expect(screen.getByText("$100")).toBeInTheDocument();
    expect(screen.getByText("$200")).toBeInTheDocument();
  });

  it("changes currency via select", () => {
    render(<PricingCards plans={plans} currencies={currencies} />);
    
    const currencySelect = screen.getByTestId("currency-select");
    fireEvent.change(currencySelect, { target: { value: "INR" } });
    
    // Check updated price display (INR, month)
    expect(screen.getByText("₹800")).toBeInTheDocument();
    expect(screen.getByText("₹1600")).toBeInTheDocument();
  });

  it("calls onSelect when a plan is chosen", () => {
    const onSelectMock = jest.fn();
    render(<PricingCards plans={plans} currencies={currencies} onSelect={onSelectMock} />);
    
    const selectNitya = screen.getByTestId("select-plan-nitya");
    fireEvent.click(selectNitya);
    
    expect(onSelectMock).toHaveBeenCalledWith("nitya", "month");
  });

  it("shows selected state for the active plan", () => {
    render(<PricingCards plans={plans} currencies={currencies} selectedPlan="nitya" onSelect={jest.fn()} />);
    
    const selectNitya = screen.getByTestId("select-plan-nitya");
    expect(selectNitya).toHaveTextContent("Selected ✓");
  });
});
