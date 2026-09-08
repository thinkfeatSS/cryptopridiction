"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

export function useKeyboardHotkeys(onEscape?: () => void) {
  const router = useRouter();
  const [showHotkeysModal, setShowHotkeysModal] = useState(false);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const activeTag = (document.activeElement?.tagName || "").toLowerCase();
      const isInputFocused = activeTag === "input" || activeTag === "textarea" || activeTag === "select";

      // Allow ESC even if input is focused
      if (e.key === "Escape") {
        if (onEscape) onEscape();
        setShowHotkeysModal(false);
        return;
      }

      // If user is typing in search input, don't trigger number hotkeys
      if (isInputFocused) return;

      if (e.key === "/") {
        e.preventDefault();
        const searchInput = document.querySelector('input[type="text"]') as HTMLInputElement;
        if (searchInput) {
          searchInput.focus();
          searchInput.select();
        }
      } else if (e.key === "1") {
        router.push("/");
      } else if (e.key === "2") {
        router.push("/signals");
      } else if (e.key === "3") {
        router.push("/portfolio");
      } else if (e.key === "4") {
        router.push("/radar");
      } else if (e.key === "?") {
        e.preventDefault();
        setShowHotkeysModal((prev) => !prev);
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [router, onEscape]);

  return {
    showHotkeysModal,
    setShowHotkeysModal,
  };
}
