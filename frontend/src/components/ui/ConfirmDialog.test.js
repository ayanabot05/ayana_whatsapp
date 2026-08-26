import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ConfirmDialog } from "./ConfirmDialog";

describe("ConfirmDialog", () => {
  it("renders trigger button and opens dialog", async () => {
    render(
      <ConfirmDialog
        trigger={<button>Delete</button>}
        title="Delete Item"
        description="Are you sure?"
        onConfirm={jest.fn()}
      />
    );
    const triggerBtn = screen.getByText("Delete");
    fireEvent.click(triggerBtn);
    
    expect(await screen.findByText("Delete Item")).toBeInTheDocument();
    expect(screen.getByText("Are you sure?")).toBeInTheDocument();
  });

  it("calls onConfirm when confirm action is clicked", async () => {
    const onConfirmMock = jest.fn().mockResolvedValue();
    render(
      <ConfirmDialog
        trigger={<button>Delete</button>}
        confirmLabel="Confirm Delete"
        onConfirm={onConfirmMock}
      />
    );
    
    fireEvent.click(screen.getByText("Delete"));
    const confirmBtn = await screen.findByTestId("confirm-action");
    
    fireEvent.click(confirmBtn);
    expect(onConfirmMock).toHaveBeenCalled();
  });

  it("closes dialog when cancel is clicked", async () => {
    render(
      <ConfirmDialog
        trigger={<button>Delete</button>}
        onConfirm={jest.fn()}
      />
    );
    
    fireEvent.click(screen.getByText("Delete"));
    const cancelBtn = await screen.findByTestId("confirm-cancel");
    fireEvent.click(cancelBtn);
    
    // Alert dialog handles closing via radix-ui, which takes it out of the DOM
    await waitFor(() => {
      expect(screen.queryByTestId("confirm-cancel")).not.toBeInTheDocument();
    });
  });
});
