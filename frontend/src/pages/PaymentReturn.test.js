import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PaymentSuccess, PaymentCancel } from "./PaymentReturn";
import { api } from "../lib/api";
import { MemoryRouter, useNavigate, useSearchParams } from "react-router-dom";

jest.mock("../lib/api");
jest.mock("react-router-dom", () => ({
  ...jest.requireActual("react-router-dom"),
  useNavigate: jest.fn(),
  useSearchParams: jest.fn(),
}));

describe("PaymentReturn Components", () => {
  const mockNavigate = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
    useNavigate.mockReturnValue(mockNavigate);
  });

  describe("PaymentSuccess", () => {
    test("shows paid state and dashboard link when payment succeeds", async () => {
      useSearchParams.mockReturnValue([new URLSearchParams("?session_id=cs_test_123")]);
      api.get.mockResolvedValueOnce({ data: { payment_status: "paid" } });

      render(<MemoryRouter><PaymentSuccess /></MemoryRouter>);

      await waitFor(() => {
        expect(screen.getByTestId("payment-paid")).toBeInTheDocument();
        expect(screen.getByText("Payment successful 🎉")).toBeInTheDocument();
      });

      await userEvent.click(screen.getByTestId("payment-go-dashboard"));
      expect(mockNavigate).toHaveBeenCalledWith("/dashboard");
    });

    test("shows failed state when payment fails", async () => {
      useSearchParams.mockReturnValue([new URLSearchParams("?session_id=cs_test_123")]);
      api.get.mockResolvedValueOnce({ data: { payment_status: "failed" } });

      render(<MemoryRouter><PaymentSuccess /></MemoryRouter>);

      await waitFor(() => {
        expect(screen.getByTestId("payment-failed")).toBeInTheDocument();
        expect(screen.getByText("Payment not completed")).toBeInTheDocument();
      });
    });

    test("shows timeout state after multiple retries", async () => {
      useSearchParams.mockReturnValue([new URLSearchParams("?session_id=cs_test_123")]);
      api.get.mockResolvedValue({ data: { payment_status: "pending" } });
      
      // Speed up timers for testing
      jest.useFakeTimers();
      
      render(<MemoryRouter><PaymentSuccess /></MemoryRouter>);
      
      // Fast-forward through 8 polling attempts (8 * 2000ms)
      jest.advanceTimersByTime(16000);
      
      await waitFor(() => {
        expect(screen.getByTestId("payment-failed")).toBeInTheDocument();
        expect(screen.getByText("Still processing")).toBeInTheDocument();
      });
      
      jest.useRealTimers();
    });
  });

  describe("PaymentCancel", () => {
    test("shows cancel message and dashboard link", async () => {
      render(<MemoryRouter><PaymentCancel /></MemoryRouter>);
      
      expect(screen.getByTestId("payment-cancel")).toBeInTheDocument();
      expect(screen.getByText("Checkout cancelled")).toBeInTheDocument();
      
      await userEvent.click(screen.getByText("Back to dashboard"));
      expect(mockNavigate).toHaveBeenCalledWith("/dashboard");
    });
  });
});
