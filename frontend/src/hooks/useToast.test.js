import { renderHook, act } from "@testing-library/react";
import { useToast, toast, reducer } from "./use-toast";

describe("useToast Hook", () => {
  beforeEach(() => {
    // Dismiss all toasts before each test to start fresh
    act(() => {
      toast({ title: "Clear" }); // generate one to dismiss all
      const { dismiss } = renderHook(() => useToast()).result.current;
      dismiss();
    });
  });

  test("reducer adds a toast", () => {
    const initialState = { toasts: [] };
    const action = { type: "ADD_TOAST", toast: { id: "1", title: "Test Toast" } };
    const state = reducer(initialState, action);
    expect(state.toasts).toHaveLength(1);
    expect(state.toasts[0].id).toBe("1");
  });

  test("reducer updates a toast", () => {
    const initialState = { toasts: [{ id: "1", title: "Test Toast", open: true }] };
    const action = { type: "UPDATE_TOAST", toast: { id: "1", title: "Updated Toast" } };
    const state = reducer(initialState, action);
    expect(state.toasts[0].title).toBe("Updated Toast");
  });

  test("reducer dismisses a toast", () => {
    const initialState = { toasts: [{ id: "1", title: "Test Toast", open: true }] };
    const action = { type: "DISMISS_TOAST", toastId: "1" };
    const state = reducer(initialState, action);
    expect(state.toasts[0].open).toBe(false);
  });

  test("reducer removes a toast", () => {
    const initialState = { toasts: [{ id: "1", title: "Test Toast", open: false }] };
    const action = { type: "REMOVE_TOAST", toastId: "1" };
    const state = reducer(initialState, action);
    expect(state.toasts).toHaveLength(0);
  });

  test("useToast limits visible toasts to 1", () => {
    const { result } = renderHook(() => useToast());

    act(() => {
      toast({ title: "First Toast" });
    });
    expect(result.current.toasts).toHaveLength(1);
    expect(result.current.toasts[0].title).toBe("First Toast");

    act(() => {
      toast({ title: "Second Toast" });
    });
    // The hook enforces TOAST_LIMIT = 1
    expect(result.current.toasts).toHaveLength(1);
    expect(result.current.toasts[0].title).toBe("Second Toast");
  });
});
