import React from "react";
import '@testing-library/jest-dom';
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
jest.mock('react-router-dom', () => ({
  MemoryRouter: ({children}) => <>{children}</>,
  Link: ({to, children, ...props}) => <a href={to} {...props}>{children}</a>,
  useNavigate: () => jest.fn(),
  useSearchParams: () => [new URLSearchParams(), jest.fn()],
  useLocation: () => ({pathname:'/dashboard',search:''}),
}));

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
  CareTab: () => <div data-testid="mock-care-tab">Care Tab Content</div>,
  VacationCard: () => <div data-testid="mock-vacation-card" />,
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
      if (url === "/dashboard/bootstrap") return Promise.resolve({ data: {
        parents: [{ id: "p1", name: "Amma", relationship: "mother", language: "en", language_suggestion: "te", phone: "+91" }],
        schedules: [{ id: "s1", parent_id: "p1", active: true, messages: [] }],
        checkins: { parents: [], alerts: [] },
        activation: { whatsapp_activated: true },
        payment: { state: { plan: "nitya", status: "trial" }, plans: [{ id: "nitya", name: "Nitya", limits: { parents: 1, checkins: 2, reminders: 2 } }], usage: {} },
        circle: { role: "owner", members: [], invites: [] },
        audit: [],
        moments_quota: { used: 0, limit: 2, remaining: 2 },
        moments: [],
      } });
      if (url.includes("/checkins")) return Promise.resolve({ data: { parents: [], alerts: [] } });
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
      expect(await screen.findByRole('heading', {name: /Hello, Test/i})).toBeInTheDocument();
    });

    test("renders 4 stat cards", async () => {
      renderDashboard();
      await waitFor(() => {
        expect(screen.getByTestId("dashboard-stats")).toBeInTheDocument();
      });
      // Parents, Schedules, Messages, Care Circle
      const stats = screen.getByTestId('dashboard-stats');
      for (const label of ['Parents', 'Active schedules', 'Messages sent (7d)', 'Care circle']) {
        expect(stats).toHaveTextContent(label);
      }
    });
  });

  describe("Parents Tab", () => {
    test('initial request failure shows an error instead of an empty parent list', async () => {
      api.get.mockRejectedValue(new Error('Network unavailable'));
      renderDashboard();
      expect(await screen.findByRole('alert', {}, {timeout: 5000})).toHaveTextContent('could not be loaded');
      expect(screen.queryByText('No parents added yet.')).not.toBeInTheDocument();
      expect(api.delete).not.toHaveBeenCalled();
    });

    test('failed refresh retains the previously loaded parent', async () => {
      renderDashboard();
      expect(await screen.findByText('Amma')).toBeInTheDocument();
      api.get.mockRejectedValue(new Error('Network unavailable'));
      await queryClient.invalidateQueries({queryKey:['dashboard']});
      expect(await screen.findByRole('alert')).toHaveTextContent('Showing your last loaded data');
      expect(screen.getByText('Amma')).toBeInTheDocument();
      expect(api.delete).not.toHaveBeenCalled();
    });

    test("cancelling removal leaves the parent intact", async () => {
      renderDashboard();
      await userEvent.click(await screen.findByTestId('delete-parent-p1'));
      expect(await screen.findByRole('alertdialog')).toHaveTextContent('Remove Amma?');
      expect(api.delete).not.toHaveBeenCalled();
      await userEvent.click(screen.getByTestId('confirm-cancel'));
      expect(screen.getByText('Amma')).toBeInTheDocument();
      expect(api.delete).not.toHaveBeenCalled();
    });

    test("refetch preserves the parent without deletion requests", async () => {
      renderDashboard();
      expect(await screen.findByText('Amma')).toBeInTheDocument();
      await queryClient.invalidateQueries({queryKey:['dashboard']});
      expect(await screen.findByText('Amma')).toBeInTheDocument();
      expect(api.delete).not.toHaveBeenCalled();
    });
    test("renders parents list", async () => {
      renderDashboard();
      await waitFor(() => {
        expect(screen.getByTestId("parents-list")).toBeInTheDocument();
        expect(screen.getByText("Amma")).toBeInTheDocument();
      });
    });

    test("shows the saved parent language without replacing it with a suggestion", async () => {
      renderDashboard();
      expect(await screen.findByTestId('parents-list')).toHaveTextContent('English');
      expect(api.patch).not.toHaveBeenCalled();
    });
  });

  describe("Check-ins Tab", () => {
    test("renders checkins tab content when clicked", async () => {
      renderDashboard();
      await waitFor(() => {
        expect(screen.getByTestId("tab-checkins")).toBeInTheDocument();
      });
      await userEvent.click(screen.getByTestId("tab-checkins"));
      expect(await screen.findByTestId("unified-checkins")).toBeInTheDocument();
    });
  });

  describe("Care Circle Tab", () => {
    test("renders circle tab and shows form", async () => {
      renderDashboard();
      await waitFor(() => screen.getByTestId("tab-circle"));
      await userEvent.click(screen.getByTestId("tab-circle"));
      expect(await screen.findByRole('heading', {name: /Family co-care/i})).toBeInTheDocument();
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
