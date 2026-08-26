import React from "react";
import { render, screen } from "@testing-library/react";
import { BrowserRouter } from "react-router-dom";
import { Footer } from "./Footer";

describe("Footer", () => {
  it("renders footer branding text", () => {
    render(
      <BrowserRouter>
        <Footer />
      </BrowserRouter>
    );
    expect(screen.getByText(/A warm care companion that helps you stay close to your parents/i)).toBeInTheDocument();
  });

  it("renders links for Product and Trust & Safety", () => {
    render(
      <BrowserRouter>
        <Footer />
      </BrowserRouter>
    );
    expect(screen.getByText("How it works")).toBeInTheDocument();
    expect(screen.getByText("Privacy Policy")).toBeInTheDocument();
    expect(screen.getByText("Terms of Use")).toBeInTheDocument();
  });

  it("renders copyright with current year", () => {
    render(
      <BrowserRouter>
        <Footer />
      </BrowserRouter>
    );
    const year = new Date().getFullYear();
    expect(screen.getByText(new RegExp(`© ${year} AYANA. Made with care.`))).toBeInTheDocument();
  });
});
