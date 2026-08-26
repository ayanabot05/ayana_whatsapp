import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { PaginationBar } from "./PaginationBar";

describe("PaginationBar", () => {
  it("renders pagination details correctly", () => {
    render(<PaginationBar skip={0} limit={10} total={25} onSkip={jest.fn()} />);
    expect(screen.getByText("1–10 of 25")).toBeInTheDocument();
    expect(screen.getByText("1 / 3")).toBeInTheDocument();
  });

  it("disables prev button on first page", () => {
    render(<PaginationBar skip={0} limit={10} total={25} onSkip={jest.fn()} />);
    const prevButton = screen.getByLabelText("Previous page");
    const nextButton = screen.getByLabelText("Next page");
    expect(prevButton).toBeDisabled();
    expect(nextButton).not.toBeDisabled();
  });

  it("disables next button on last page", () => {
    render(<PaginationBar skip={20} limit={10} total={25} onSkip={jest.fn()} />);
    const prevButton = screen.getByLabelText("Previous page");
    const nextButton = screen.getByLabelText("Next page");
    expect(prevButton).not.toBeDisabled();
    expect(nextButton).toBeDisabled();
  });

  it("calls onSkip with correct values on button clicks", () => {
    const onSkipMock = jest.fn();
    render(<PaginationBar skip={10} limit={10} total={25} onSkip={onSkipMock} />);
    
    const prevButton = screen.getByLabelText("Previous page");
    const nextButton = screen.getByLabelText("Next page");
    
    fireEvent.click(prevButton);
    expect(onSkipMock).toHaveBeenCalledWith(0);
    
    fireEvent.click(nextButton);
    expect(onSkipMock).toHaveBeenCalledWith(20);
  });

  it("returns null when total is 0", () => {
    const { container } = render(<PaginationBar skip={0} limit={10} total={0} onSkip={jest.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });
});
