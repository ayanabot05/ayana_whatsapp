import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import Activation from "./Activation";
import { api } from "../lib/api";
import { useAuth } from "../context/AuthContext";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

jest.mock("../lib/api");
jest.mock("../context/AuthContext");

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false } },
});

describe("Activation Component", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    useAuth.mockReturnValue({
      config: {
        whatsapp_enabled: true,
        training_video_url: "https://example.com/video",
        reply_options: [
          { value: "1", label: { en: "Good" } },
          { value: "2", label: { en: "Okay" } }
        ]
      }
    });
    api.get.mockImplementation((url) => {
      if (url === "/parents") {
        return Promise.resolve({
          data: [
            { id: "p1", name: "Amma", phone: "+919876543210" }
          ]
        });
      }
      return Promise.resolve({ data: {} });
    });
  });

  test("renders parent list with wa.me links", async () => {
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <Activation />
        </MemoryRouter>
      </QueryClientProvider>
    );

    expect(screen.getByText(/Your care circle is active/i)).toBeInTheDocument();
    
    await waitFor(() => {
      const waLink = screen.getByTestId("wa-link-p1");
      expect(waLink).toBeInTheDocument();
      expect(waLink).toHaveAttribute("href", "https://wa.me/919876543210");
    });
  });

  test("shows test mode banner if whatsapp_enabled is false", async () => {
    useAuth.mockReturnValue({
      config: { whatsapp_enabled: false }
    });

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <Activation />
        </MemoryRouter>
      </QueryClientProvider>
    );

    expect(screen.getByTestId("testmode-banner")).toBeInTheDocument();
  });

  test("renders video player if training_video_url is provided", async () => {
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <Activation />
        </MemoryRouter>
      </QueryClientProvider>
    );

    expect(screen.getByTestId("training-video")).toBeInTheDocument();
  });
});
