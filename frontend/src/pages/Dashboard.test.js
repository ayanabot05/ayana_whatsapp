import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Dashboard from "./Dashboard";
import { api } from "../lib/api";
import { useAuth } from "../context/AuthContext";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { toast } from "sonner";

jest.mock("../lib/api");
jest.mock("../context/AuthContext");
jest.mock("sonner", () => ({ toast: { error: jest.fn(), success: jest.fn() } }));

// Mock rechart components to avoid SVG rendering issues in JSDOM
jest.mock("recharts", () => {
  const Original = jest.requireActual("recharts");
  return {
    ...Original,
    ResponsiveContainer: ({ children }) => <div>{children}</div>,
    LineChart: () => <div data-testid="line-chart" />,
  };
});

// Mock some sub-tabs to keep tests focused on the main Dashboard routing logic
jest.mock("../components/CareTab", () => ({
  CareTab: () => <div data-testid="mock-care-tab">Care Tab Content</div>
}));
jest.mock("../components/ReportsTab", () => ({
  ReportsTab: () => <div data-testid="mock-reports-tab">Reports Tab Content</div>
}));

describe("Dashboard Component", () => {
  let queryClient;

  beforeEach(() => {
    jest.clearAllMocks();
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    useAuth.mockReturnValue({
      user: { name: "Test User", phone: "+123", phone_verified: true, onboarding_step: 5 },
      config: {
        feeling_map: {},
        categories: [{ key: "morning", label: "Morning" }],
        relationships: ["mother"],
        languages: [{ code: "en", label: "English" }]
      },
      logout: jest.fn(),
      refreshUser: jest.fn()
    });

    api.get.mockImplementation((url) => {
      if (url === "/parents") return Promise.resolve({ data: [{ id: "p1", name: "Amma", relationship: "mother", language: "en", phone: "+91" }] });
      if (url.includes("language-suggestion")) return Promise.resolve({ data: "te" });
      if (url === "/schedules") return Promise.resolve({ data: [{ id: "s1", parent_id: "p1", active: true, messages: [] }] });
      if (url.includes("/checkins")) return Promise.resolve({ data: { parents: [], alerts: [] } });
      if (url === "/activation") return Promise.resolve({ data: { whatsapp_activated: true } });
      if (url === "/payment/state") return Promise.resolve({ data: { plan: "nitya", plans: [{ id: "nitya", name: "Nitya" }] } });
      if (url === "/circle") return Promise.resolve({ data: { role: "owner", members: [], invites: [] } });
      if (url === "/account/audit") return Promise.resolve({ data: [] });
      return Promise.resolve({ data: {} });
    });
  });

  const renderDashboard = () => render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>
    </QueryClientProvider>
  );

  describe("Main Layout & Stats", () => {
    test("renders header with user name", async () => {
      renderDashboard();
      expect(await screen.findByText(/Hello, Test/i)).toBeInTheDocument();
    });

    test("renders 4 stat cards", async () => {
      renderDashboard();
      await waitFor(() => {
        expect(screen.getByTestId("dashboard-stats")).toBeInTheDocument();
      });
      // Parents, Schedules, Messages, Care Circle
      expect(screen.getByText("Parents")).toBeInTheDocument();
      expect(screen.getByText("Active schedules")).toBeInTheDocument();
      expect(screen.getByText("Messages sent (7d)")).toBeInTheDocument();
      expect(screen.getByText("Care circle")).toBeInTheDocument();
    });
  });

  describe("Parents Tab", () => {
    test("renders parents list", async () => {
      renderDashboard();
      await waitFor(() => {
        expect(screen.getByTestId("parents-list")).toBeInTheDocument();
        expect(screen.getByText("Amma")).toBeInTheDocument();
      });
    });

    test("shows language suggestions if available", async () => {
      renderDashboard();
      await waitFor(() => {
        expect(screen.getByText(/Detected Telugu/i)).toBeInTheDocument();
        expect(screen.getByTestId("apply-lang-p1")).toBeInTheDocument();
      });
    });
  });

  describe("Check-ins Tab", () => {
    test("renders checkins tab content when clicked", async () => {
      renderDashboard();
      await waitFor(() => {
        expect(screen.getByTestId("tab-checkins")).toBeInTheDocument();
      });
      await userEvent.click(screen.getByTestId("tab-checkins"));
      expect(await screen.findByTestId("checkins-empty")).toBeInTheDocument();
    });
  });

  describe("Care Circle Tab", () => {
    test("renders circle tab and shows form", async () => {
      renderDashboard();
      await waitFor(() => screen.getByTestId("tab-circle"));
      await userEvent.click(screen.getByTestId("tab-circle"));
      expect(await screen.findByText(/Family co-care/i)).toBeInTheDocument();
    });
  });

  describe("Account Tab", () => {
    test("renders account details and delete button", async () => {
      renderDashboard();
      await waitFor(() => screen.getByTestId("tab-account"));
      await userEvent.click(screen.getByTestId("tab-account"));
      
      expect(await screen.findByText(/Test User/i)).toBeInTheDocument();
      expect(screen.getByTestId("delete-account")).toBeInTheDocument();
    });
  });
});
