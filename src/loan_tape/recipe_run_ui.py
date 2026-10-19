"""Reuse the cell-review controls for one explicitly approved recipe step at a time."""

from __future__ import annotations

from pathlib import Path
from threading import Event
from typing import TYPE_CHECKING
from weakref import proxy

from loan_tape.recipe_execution import approve_excel_recipe_step, review_excel_recipe
from loan_tape.recipes import Settings, operation_settings
from loan_tape.text_cleanup import TextCleanupReview, TextCleanupSettings
from loan_tape.text_cleanup_ui import TextCleanupWindow
from loan_tape.text_rule_types import ExactRulesSettings
from loan_tape.transformations import TransformationApproval, TransformationRevision

if TYPE_CHECKING:
    from loan_tape.recipe_ui import RecipeWindow


class RecipeStepWindow(TextCleanupWindow):
    def __init__(self, manager: RecipeWindow) -> None:
        self.manager = proxy(manager)
        assert manager.running_recipe is not None and manager.binding is not None
        self.recipe, self.binding = manager.running_recipe, manager.binding
        self.step_index = len(manager.staged.to_dict()["steps"]) if manager.staged else 0
        relative, self.step_settings = operation_settings(self.recipe.steps[self.step_index])
        owner = manager.owner
        super().__init__(
            manager.window,
            owner.source,
            owner.table,
            owner.table.selection.area.min_column + relative - 1,
            owner.store,
            owner.current_table,
            owner.jump,
            owner.workers,
            lambda _: None,
            manager.staged,
        )
        self.window.title(f"Recipe review: step {self.step_index + 1} of {len(self.recipe.steps)}")
        if isinstance(self.step_settings, ExactRulesSettings):
            self.exact_settings = self.step_settings
            self.mode.set("Exact replacements")
        else:
            self.repair.set(self.step_settings.repair_encoding)
            self.normalize.set(self.step_settings.normalization == "NFC")
        self.reviewer.set(self.binding.to_dict()["reviewer"])
        self._buttons()
        self.status.set(
            "Preview this step, inspect all outcomes, and choose cells. Approve with no choices to leave this step unchanged."
        )

    def _settings(self) -> Settings:
        return self.step_settings

    def _buttons(self) -> None:
        super()._buttons()
        for widget in (
            self.mode_box,
            self.repair_check,
            self.normalize_check,
            self.rule_button,
            self.recipe_button,
            self.export_button,
        ):
            widget.configure(state="disabled")
        last = self.step_index == len(self.recipe.steps) - 1
        self.apply_button.configure(
            text="Approve and publish recipe" if last else "Approve step",
            state="normal"
            if self.review is not None and self.allowed and not self.busy and not self.applied
            else "disabled",
        )
        self.reset_button.configure(text="Discard recipe run", command=self.close, state="normal")
        self.result_label.set(
            f"Recipe step {self.step_index + 1} of {len(self.recipe.steps)}. Earlier approvals are staged only; the final step publishes the complete run."
        )

    def _can_approve_empty(self) -> bool:
        return True

    def _review_current(
        self,
        settings: TextCleanupSettings | ExactRulesSettings,
        parent: TransformationRevision | None,
        cancelled: Event,
    ) -> TextCleanupReview:
        return review_excel_recipe(
            self.source,
            self.table,
            self.store,
            self.recipe,
            self.binding,
            parent=parent,
            cancelled=cancelled,
        )

    def _apply_current(
        self,
        settings: TextCleanupSettings | ExactRulesSettings,
        review: TextCleanupReview,
        approval: TransformationApproval,
        parent: TransformationRevision | None,
        cancelled: Event,
    ) -> tuple[TransformationRevision, Path | None]:
        return approve_excel_recipe_step(
            self.source,
            self.table,
            self.store,
            self.recipe,
            self.binding,
            review,
            approval,
            parent=parent,
            cancelled=cancelled,
        )

    def _received_application(self, revision: TransformationRevision, path: Path | None) -> None:
        self.manager.step_approved(revision, path)

    def _received_error(self, error: Exception) -> None:
        self.manager.discard_run(f"Recipe stopped; staged approvals discarded: {error}")

    def cancel(self) -> None:
        self.manager.discard_run("Recipe cancelled; staged approvals discarded.")

    def close(self, *, discard: bool = True) -> None:
        if self.closed:
            return
        super().close()
        if discard and not self.manager.closed:
            self.manager.discard_run("Recipe review closed; staged approvals discarded.")
