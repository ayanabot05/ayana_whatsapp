import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { PhoneInput } from "./PhoneInput";

describe("PhoneInput", () => {
  it("renders properly with default placeholder", () => {
    render(<PhoneInput value="" onChange={jest.fn()} testid="phone-input" />);
    expect(screen.getByTestId("phone-input")).toBeInTheDocument();
    expect(screen.getByTestId("phone-input-code")).toBeInTheDocument();
  });

  it("initializes dial code and number correctly from value", () => {
    render(<PhoneInput value="+14155552671" onChange={jest.fn()} testid="phone-input" />);
    expect(screen.getByTestId("phone-input-code")).toHaveValue("+1");
    expect(screen.getByTestId("phone-input")).toHaveValue("4155552671");
  });

  it("calls onChange with formatted full number when number is updated", () => {
    const onChangeMock = jest.fn();
    render(<PhoneInput value="+919876543210" onChange={onChangeMock} testid="phone-input" />);
    
    const input = screen.getByTestId("phone-input");
    fireEvent.change(input, { target: { value: "9876543211" } });
    
    expect(onChangeMock).toHaveBeenCalledWith("+919876543211");
  });

  it("calls onChange with formatted full number when country code is updated", () => {
    const onChangeMock = jest.fn();
    render(<PhoneInput value="+919876543210" onChange={onChangeMock} testid="phone-input" />);
    
    const select = screen.getByTestId("phone-input-code");
    fireEvent.change(select, { target: { value: "+1" } });
    
    expect(onChangeMock).toHaveBeenCalledWith("+19876543210");
  });

  it("strips non-numeric characters from input", () => {
    const onChangeMock = jest.fn();
    render(<PhoneInput value="+91" onChange={onChangeMock} testid="phone-input" />);
    
    const input = screen.getByTestId("phone-input");
    fireEvent.change(input, { target: { value: "12a3b4c" } });
    
    expect(input).toHaveValue("1234");
    expect(onChangeMock).toHaveBeenCalledWith("+911234");
  });
});
