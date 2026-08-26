import React from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Landing from "./Landing";
import { useAuth } from "../context/AuthContext";
import { useLang } from "../context/LanguageContext";
import { MemoryRouter } from "react-router-dom";

jest.mock("../context/AuthContext");
jest.mock("../context/LanguageContext");
jest.mock("../components/StartConnectingModal", () => ({
  StartConnectingModal: ({ open }) => (open ? <div data-testid="start-modal">Modal Open</div> : null),
}));
jest.mock("../components/PhoneMockup", () => ({
  PhoneMockup: () => <div data-testid="phone-mockup">Phone Mockup</div>,
}));

describe("Landing Component", () => {
  const mockSetLang = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
    useAuth.mockReturnValue({
      config: {
        plans: [{ id: "test-plan", name: "Test Plan", prices: {} }],
        currencies: [{ code: "USD", symbol: "$" }],
      },
    });
    useLang.mockReturnValue({
      lang: "en",
      setLang: mockSetLang,
      t: (key) => {
        const translations = {
          "how.steps": [{ title: "Step 1", desc: "Desc 1" }],
          "faq.items": [{ q: "Q1", a: "A1" }],
          "global.points": ["Point 1", "Point 2"],
          "training.steps": [{ title: "TStep 1", desc: "TDesc 1" }],
        };
        return translations[key] || key;
      },
    });
  });

  test("renders hero, features, and language switcher", () => {
    render(<MemoryRouter><Landing /></MemoryRouter>);
    
    expect(screen.getByTestId("lang-switcher")).toBeInTheDocument();
    expect(screen.getByTestId("hero-cta")).toBeInTheDocument();
    expect(screen.getByTestId("faq-accordion")).toBeInTheDocument();
  });

  test("language switcher calls setLang", async () => {
    render(<MemoryRouter><Landing /></MemoryRouter>);
    
    const teButton = screen.getByTestId("lang-switcher-te");
    await userEvent.click(teButton);
    
    expect(mockSetLang).toHaveBeenCalledWith("te");
  });

  test("opens CTA modal when clicking primary CTA", async () => {
    render(<MemoryRouter><Landing /></MemoryRouter>);
    
    expect(screen.queryByTestId("start-modal")).not.toBeInTheDocument();
    
    await userEvent.click(screen.getByTestId("hero-cta"));
    
    expect(screen.getByTestId("start-modal")).toBeInTheDocument();
  });
});
