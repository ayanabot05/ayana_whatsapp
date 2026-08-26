import React from "react";
import { render, act } from "@testing-library/react";
import { LanguageProvider, useLang } from "./LanguageContext";
import { useAuth } from "./AuthContext";

jest.mock("./AuthContext", () => ({
  useAuth: jest.fn(),
}));

jest.mock("../lib/translations", () => ({
  translations: {
    en: {
      hello: "Hello",
      nested: {
        key: "Nested Key EN"
      }
    },
    te: {
      hello: "నమస్కారం",
      nested: {
        key: "Nested Key TE"
      }
    }
  }
}));

const TestComponent = () => {
  const { lang, setLang, t } = useLang();
  return (
    <div>
      <span data-testid="lang">{lang}</span>
      <span data-testid="t-hello">{t("hello")}</span>
      <span data-testid="t-nested">{t("nested.key")}</span>
      <span data-testid="t-missing">{t("missing.key")}</span>
      <button data-testid="set-te" onClick={() => setLang("te")}>Set TE</button>
    </div>
  );
};

describe("LanguageContext", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    localStorage.clear();
    useAuth.mockReturnValue({ user: null });
  });

  test("uses default en and translates keys", () => {
    const { getByTestId } = render(
      <LanguageProvider>
        <TestComponent />
      </LanguageProvider>
    );

    expect(getByTestId("lang").textContent).toBe("en");
    expect(getByTestId("t-hello").textContent).toBe("Hello");
    expect(getByTestId("t-nested").textContent).toBe("Nested Key EN");
    // Missing key returns raw key
    expect(getByTestId("t-missing").textContent).toBe("missing.key");
  });

  test("setLang persists to localStorage and updates translations", () => {
    const { getByTestId } = render(
      <LanguageProvider>
        <TestComponent />
      </LanguageProvider>
    );

    act(() => {
      getByTestId("set-te").click();
    });

    expect(getByTestId("lang").textContent).toBe("te");
    expect(getByTestId("t-hello").textContent).toBe("నమస్కారం");
    expect(localStorage.getItem("ayana_lang")).toBe("te");
  });

  test("syncs from user.preferences.language", () => {
    useAuth.mockReturnValue({
      user: { preferences: { language: "te" } }
    });

    const { getByTestId } = render(
      <LanguageProvider>
        <TestComponent />
      </LanguageProvider>
    );

    expect(getByTestId("lang").textContent).toBe("te");
    expect(getByTestId("t-hello").textContent).toBe("నమస్కారం");
  });
});
