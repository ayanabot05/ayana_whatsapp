import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { ScheduleEditor, normalizeCategory, CATEGORY_ICONS } from "./ScheduleEditor";
import { toast } from "sonner";

jest.mock("sonner", () => ({ toast: { error: jest.fn() } }));

describe("ScheduleEditor", () => {
  const categories = [
    { key: "morning_wish", label: "Morning Wish", type: "checkin", icon: "sunrise" },
    { key: "breakfast", label: "Breakfast Check", type: "checkin", icon: "coffee" },
  ];

  it("normalizes category object correctly", () => {
    const raw = { key: "lunch" };
    const normalized = normalizeCategory(raw);
    expect(normalized.key).toBe("lunch");
    expect(normalized.label).toBe("Lunch Check");
    expect(normalized.icon).toBe("utensils");
  });

  it("renders loading state if no categories", () => {
    render(<ScheduleEditor messages={[]} setMessages={jest.fn()} categories={[]} maxCheckins={2} />);
    expect(screen.getByText(/Loading schedule categories/i)).toBeInTheDocument();
  });

  it("renders checkins list and adds a checkin", () => {
    const setMessagesMock = jest.fn();
    render(<ScheduleEditor messages={[]} setMessages={setMessagesMock} categories={categories} maxCheckins={2} />);
    
    expect(screen.getByText(/No check-ins yet/i)).toBeInTheDocument();
    
    const addBtn = screen.getByTestId("add-checkin");
    fireEvent.click(addBtn);
    
    expect(setMessagesMock).toHaveBeenCalledWith([
      { time: "09:00", category: "morning_wish", type: "checkin" }
    ]);
  });

  it("enforces maxCheckins limit", () => {
    const messages = [
      { time: "09:00", category: "morning_wish", type: "checkin" },
      { time: "13:00", category: "breakfast", type: "checkin" },
    ];
    render(<ScheduleEditor messages={messages} setMessages={jest.fn()} categories={categories} maxCheckins={2} />);
    
    const addBtn = screen.getByTestId("add-checkin");
    expect(addBtn).toBeDisabled();
    
    fireEvent.click(addBtn);
    // Because it's disabled, click won't trigger or it'll fail in component. Let's test the component function manually or simulate enabled click
    // Actually, button is disabled so fireEvent.click might not do anything. But if it did, it should toast.
    // Let's force it by passing maxCheckins={2} but rendering with 2 items.
  });

  it("removes a checkin", () => {
    const messages = [
      { time: "09:00", category: "morning_wish", type: "checkin" },
      { time: "13:00", category: "breakfast", type: "checkin" },
    ];
    const setMessagesMock = jest.fn();
    render(<ScheduleEditor messages={messages} setMessages={setMessagesMock} categories={categories} maxCheckins={2} />);
    
    const removeBtn = screen.getByTestId("sched-remove-0");
    fireEvent.click(removeBtn);
    
    expect(setMessagesMock).toHaveBeenCalledWith([
      { time: "13:00", category: "breakfast", type: "checkin" }
    ]);
  });
});
