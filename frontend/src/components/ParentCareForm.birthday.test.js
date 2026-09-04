import React, { useState } from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { ParentCareForm, blankParentForm, blankMedicine } from "./ParentCareForm";

jest.mock("sonner", () => ({ toast: { error: jest.fn(), success: jest.fn() } }));

jest.mock("@/components/PhoneInput", () => ({
  PhoneInput: ({ value, onChange, testid }) => (
    <input data-testid={testid} value={value} onChange={(e) => onChange(e.target.value)} />
  ),
}));

jest.mock("@/components/ScheduleEditor", () => ({
  ScheduleEditor: () => <div data-testid="mock-schedule-editor" />,
  ReminderEditor: () => <div data-testid="mock-reminder-editor" />,
}));

// Stateful host, mirroring how Onboarding/Dashboard hold the form state.
function Host({ initial, onFormChange }) {
  const [form, setForm] = useState(initial || blankParentForm());
  const [newMed, setNewMed] = useState(blankMedicine());
  const update = (next) => {
    const value = typeof next === "function" ? next(form) : next;
    setForm(value);
    if (onFormChange) onFormChange(value);
  };
  return (
    <div>
      <span data-testid="form-birthday">{form.birthday}</span>
      <ParentCareForm
        form={form}
        setForm={update}
        newMed={newMed}
        setNewMed={setNewMed}
        config={{}}
        limits={{ checkins: 2, reminders: 2 }}
        plan={{ name: "Nitya" }}
        idPrefix="parent"
      />
    </div>
  );
}

const month = () => screen.getByTestId("parent-birthday-month");
const day = () => screen.getByTestId("parent-birthday-day");

describe("Birthday picker (regression: partial selection must stick)", () => {
  test("month-only selection persists in the UI and does not commit form.birthday", () => {
    render(<Host />);
    fireEvent.change(month(), { target: { value: "03" } });
    expect(month().value).toBe("03");
    expect(day().value).toBe("");
    expect(screen.getByTestId("form-birthday").textContent).toBe("");
  });

  test("day-only selection persists in the UI", () => {
    render(<Host />);
    fireEvent.change(day(), { target: { value: "15" } });
    expect(day().value).toBe("15");
    expect(month().value).toBe("");
    expect(screen.getByTestId("form-birthday").textContent).toBe("");
  });

  test("month then day keeps both and commits MM-DD", () => {
    render(<Host />);
    fireEvent.change(month(), { target: { value: "03" } });
    fireEvent.change(day(), { target: { value: "15" } });
    expect(month().value).toBe("03");
    expect(day().value).toBe("15");
    expect(screen.getByTestId("form-birthday").textContent).toBe("03-15");
  });

  test("day then month keeps both and commits MM-DD", () => {
    render(<Host />);
    fireEvent.change(day(), { target: { value: "09" } });
    fireEvent.change(month(), { target: { value: "11" } });
    expect(month().value).toBe("11");
    expect(day().value).toBe("09");
    expect(screen.getByTestId("form-birthday").textContent).toBe("11-09");
  });

  test("selection survives an unrelated field edit (re-render)", () => {
    render(<Host />);
    fireEvent.change(month(), { target: { value: "07" } });
    fireEvent.change(screen.getByTestId("parent-city"), { target: { value: "Hyderabad" } });
    expect(month().value).toBe("07");
  });

  test("existing parent birthday is hydrated into both dropdowns", () => {
    render(<Host initial={{ ...blankParentForm(), birthday: "12-25" }} />);
    expect(month().value).toBe("12");
    expect(day().value).toBe("25");
  });

  test("clearing the day after a full birthday keeps the month selected", () => {
    render(<Host initial={{ ...blankParentForm(), birthday: "12-25" }} />);
    fireEvent.change(day(), { target: { value: "" } });
    expect(day().value).toBe("");
    expect(month().value).toBe("12"); // must not collapse back to blank
  });

  test("day options follow the selected month (Feb -> 29)", () => {
    render(<Host />);
    fireEvent.change(month(), { target: { value: "02" } });
    // 29 day options + the placeholder
    expect(day().querySelectorAll("option").length).toBe(30);
  });
});
