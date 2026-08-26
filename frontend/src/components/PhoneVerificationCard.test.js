import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { PhoneVerificationCard } from "./PhoneVerificationCard";
import { toast } from "sonner";

jest.mock("sonner", () => ({
  toast: { success: jest.fn(), error: jest.fn() }
}));

describe("PhoneVerificationCard", () => {
  const defaultProps = {
    label: "Your Number",
    phone: "+919876543210",
    verified: false,
    onSend: jest.fn(),
    onVerify: jest.fn(),
    onResend: jest.fn(),
    onVerified: jest.fn(),
    testid: "verify-card",
  };

  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("renders label and phone number", () => {
    render(<PhoneVerificationCard {...defaultProps} />);
    expect(screen.getByText("Your Number")).toBeInTheDocument();
    expect(screen.getByText("+919876543210")).toBeInTheDocument();
  });

  it("renders verified badge when verified is true", () => {
    render(<PhoneVerificationCard {...defaultProps} verified={true} />);
    expect(screen.getByTestId("verify-card-verified-badge")).toBeInTheDocument();
    expect(screen.queryByTestId("verify-card-send")).not.toBeInTheDocument();
  });

  it("calls onSend when send button is clicked", async () => {
    const onSendMock = jest.fn().mockResolvedValue();
    render(<PhoneVerificationCard {...defaultProps} onSend={onSendMock} />);
    
    const sendBtn = screen.getByTestId("verify-card-send");
    fireEvent.click(sendBtn);
    
    expect(onSendMock).toHaveBeenCalledWith("+919876543210");
    await waitFor(() => {
      expect(screen.getByTestId("verify-card-code")).toBeInTheDocument();
    });
    expect(toast.success).toHaveBeenCalledWith(expect.stringContaining("+919876543210"));
  });

  it("calls onVerify with code when verify button is clicked", async () => {
    const onSendMock = jest.fn().mockResolvedValue();
    const onVerifyMock = jest.fn().mockResolvedValue();
    const onVerifiedMock = jest.fn();
    
    render(
      <PhoneVerificationCard 
        {...defaultProps} 
        onSend={onSendMock} 
        onVerify={onVerifyMock} 
        onVerified={onVerifiedMock} 
      />
    );
    
    fireEvent.click(screen.getByTestId("verify-card-send"));
    
    const input = await screen.findByTestId("verify-card-code");
    fireEvent.change(input, { target: { value: "123456" } });
    
    const verifyBtn = screen.getByTestId("verify-card-verify");
    fireEvent.click(verifyBtn);
    
    expect(onVerifyMock).toHaveBeenCalledWith("+919876543210", "123456");
    await waitFor(() => {
      expect(onVerifiedMock).toHaveBeenCalledWith("+919876543210");
    });
  });

  it("calls onResend when resend button is clicked", async () => {
    const onSendMock = jest.fn().mockResolvedValue();
    const onResendMock = jest.fn().mockResolvedValue();
    
    render(<PhoneVerificationCard {...defaultProps} onSend={onSendMock} onResend={onResendMock} />);
    
    fireEvent.click(screen.getByTestId("verify-card-send"));
    
    const resendBtn = await screen.findByTestId("verify-card-resend");
    fireEvent.click(resendBtn);
    
    expect(onResendMock).toHaveBeenCalledWith("+919876543210");
    await waitFor(() => {
      expect(toast.success).toHaveBeenCalledWith("New code sent.");
    });
  });
});
