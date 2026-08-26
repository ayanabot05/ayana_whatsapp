import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { ParentCareForm, blankParentForm, blankMedicine } from "./ParentCareForm";
import { toast } from "sonner";

jest.mock("sonner", () => ({ toast: { error: jest.fn() } }));

// Mock PhoneInput since it's tested separately
jest.mock("@/components/PhoneInput", () => ({
  PhoneInput: ({ value, onChange, testid }) => (
    <input data-testid={testid} value={value} onChange={(e) => onChange(e.target.value)} />
  )
}));

jest.mock("@/components/ScheduleEditor", () => ({
  ScheduleEditor: () => <div data-testid="mock-schedule-editor"></div>
}));

describe("ParentCareForm", () => {
  let form, setForm, newMed, setNewMed, config, limits, plan;

  beforeEach(() => {
    form = blankParentForm();
    setForm = jest.fn((fn) => {
      if (typeof fn === "function") {
        form = fn(form);
      } else {
        form = fn;
      }
    });
    newMed = blankMedicine();
    setNewMed = jest.fn((fn) => {
      newMed = typeof fn === "function" ? fn(newMed) : fn;
    });
    config = {};
    limits = { checkins: 2, reminders: 2 };
    plan = { name: "Test Plan" };
  });

  const renderForm = () => {
    return render(
      <ParentCareForm
        form={form}
        setForm={setForm}
        newMed={newMed}
        setNewMed={setNewMed}
        config={config}
        limits={limits}
        plan={plan}
      />
    );
  };

  it("renders all sections", () => {
    renderForm();
    expect(screen.getByText("1. Parent details")).toBeInTheDocument();
    expect(screen.getByText("2. Daily check-ins")).toBeInTheDocument();
    expect(screen.getByText("3. Daily routine & activities")).toBeInTheDocument();
    expect(screen.getByText("4. Medicine reminders")).toBeInTheDocument();
  });

  it("updates text fields correctly", () => {
    renderForm();
    const nameInput = screen.getByTestId("pd-name");
    fireEvent.change(nameInput, { target: { value: "Amma" } });
    expect(setForm).toHaveBeenCalledWith(expect.objectContaining({ name: "Amma" }));
  });

  it("integrates phone input", () => {
    renderForm();
    const phoneInput = screen.getByTestId("pd-phone");
    fireEvent.change(phoneInput, { target: { value: "+911234567890" } });
    expect(setForm).toHaveBeenCalledWith(expect.objectContaining({ phone: "+911234567890" }));
  });

  it("caps nicknames to max 3", () => {
    renderForm();
    const nicknamesInput = screen.getByTestId("pd-nicknames");
    fireEvent.change(nicknamesInput, { target: { value: "Amma, Mummy, Ma, Matha" } });
    expect(setForm).toHaveBeenCalledWith(expect.objectContaining({
      nicknames: ["Amma", "Mummy", "Ma"]
    }));
  });

  it("adds and removes medicines", () => {
    newMed.name = "Aspirin";
    newMed.dose = "1 tab";
    
    const { rerender } = renderForm();
    
    const addMedBtn = screen.getByTestId("pd-med-add");
    fireEvent.click(addMedBtn);
    
    // Test that setForm was called to add medicine
    expect(setForm).toHaveBeenCalled();
    const addedForm = setForm.mock.calls[0][0](blankParentForm());
    expect(addedForm.medicine_list.length).toBe(1);
    expect(addedForm.medicine_list[0].name).toBe("Aspirin");
    
    // Rerender with added med
    form = addedForm;
    rerender(
      <ParentCareForm
        form={form}
        setForm={setForm}
        newMed={blankMedicine()}
        setNewMed={setNewMed}
        config={config}
        limits={limits}
        plan={plan}
      />
    );
    
    expect(screen.getByText("Aspirin · 1 tab")).toBeInTheDocument();
    
    const removeBtn = screen.getByTestId("pd-med-remove-0");
    fireEvent.click(removeBtn);
    
    const removedForm = setForm.mock.calls[1][0](form);
    expect(removedForm.medicine_list.length).toBe(0);
  });
});
