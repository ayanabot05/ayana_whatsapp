import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import CareTab from "./CareTab";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { toast } from "sonner";

jest.mock("@/lib/api", () => ({
  api: {
    get: jest.fn(),
    post: jest.fn(),
    put: jest.fn(),
  },
  formatApiError: jest.fn(),
}));

jest.mock("sonner", () => ({ toast: { success: jest.fn(), error: jest.fn() } }));

jest.mock("@/components/PhoneInput", () => ({
  PhoneInput: ({ value, onChange, testid }) => (
    <input data-testid={testid} value={value} onChange={(e) => onChange(e.target.value)} />
  )
}));

describe("CareTab", () => {
  let queryClient;
  const parents = [{ id: "p1", name: "Amma" }];
  const schedules = [{ id: "s1", parent_id: "p1", recovery_mode: false }];

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    jest.clearAllMocks();
    
    api.get.mockImplementation((url) => {
      if (url === "/moments") return Promise.resolve({ data: [] });
      if (url.includes("/emergency-contacts")) return Promise.resolve({ data: { contacts: [] } });
      if (url.includes("/emergency-events")) return Promise.resolve({ data: [] });
      return Promise.resolve({ data: {} });
    });
  });

  const renderComponent = (planId = "raksha") => {
    return render(
      <QueryClientProvider client={queryClient}>
        <CareTab parents={parents} schedules={schedules} planId={planId} />
      </QueryClientProvider>
    );
  };

  it("renders MomentComposer and RecoveryCard", () => {
    renderComponent();
    expect(screen.getByTestId("moment-composer")).toBeInTheDocument();
    expect(screen.getByTestId("recovery-card")).toBeInTheDocument();
  });

  it("hides recovery card functionality if plan is not Raksha", () => {
    renderComponent("nitya");
    expect(screen.getByText(/Upgrade to/)).toBeInTheDocument();
    expect(screen.getAllByText(/Raksha/).length).toBeGreaterThan(0);
    expect(screen.queryByTestId("recovery-days")).not.toBeInTheDocument();
  });

  it("submits a moment", async () => {
    api.post.mockResolvedValue({ data: {} });
    renderComponent();
    
    const textArea = screen.getByTestId("moment-text");
    fireEvent.change(textArea, { target: { value: "Thinking of you!" } });
    
    const sendBtn = screen.getByTestId("moment-send");
    fireEvent.click(sendBtn);
    
    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith("/moments", expect.objectContaining({
        parent_id: "p1",
        text: "Thinking of you!",
      }));
    });
  });

  it("adds and saves emergency contacts", async () => {
    api.put.mockResolvedValue({ data: {} });
    renderComponent();
    
    // Wait for the query to finish so the add button appears
    await screen.findByTestId("emergency-add-p1");
    
    const addBtn = screen.getByTestId("emergency-add-p1");
    fireEvent.click(addBtn);
    
    const nameInput = screen.getByTestId("emergency-name-0");
    fireEvent.change(nameInput, { target: { value: "Ravi" } });
    
    const saveBtn = screen.getByTestId("emergency-save-p1");
    fireEvent.click(saveBtn);
    
    await waitFor(() => {
      expect(api.put).toHaveBeenCalledWith(
        "/parents/p1/emergency-contacts",
        expect.objectContaining({ contacts: expect.any(Array) })
      );
    });
  });

  it("renders emergency events history", async () => {
    api.get.mockImplementation((url) => {
      if (url.includes("/emergency-events")) return Promise.resolve({ data: [
        { id: "e1", keywords: ["pain"], body: "I am in pain", status: "open", created_at: new Date().toISOString() }
      ]});
      return Promise.resolve({ data: [] });
    });
    
    renderComponent();
    
    expect(await screen.findByTestId("emergency-event-e1")).toBeInTheDocument();
    expect(screen.getByText(/I am in pain/)).toBeInTheDocument();
  });
});
