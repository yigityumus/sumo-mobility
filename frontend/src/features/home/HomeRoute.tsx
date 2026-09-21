import HomePage from "../../components/HomePage.tsx";
import ModelActionDialog from "../../components/ModelActionDialog.tsx";

export default function HomeRoute({
  savedModels,
  loadingModel,
  busy,
  modelActionDialog,
  onStartNewModel,
  onOpenAnalytics,
  onDocumentation,
  onLoadSavedModel,
  onRequestDuplicateModel,
  onRequestRenameModel,
  onRequestDeleteModel,
  onCancelModelAction,
  onConfirmModelAction,
}: any) {
  return (
    <>
      <HomePage
        savedModels={savedModels}
        loadingModel={loadingModel}
        busy={busy}
        onStartNewModel={onStartNewModel}
        onOpenAnalytics={onOpenAnalytics}
        onDocumentation={onDocumentation}
        onLoadSavedModel={onLoadSavedModel}
        onRequestDuplicateModel={onRequestDuplicateModel}
        onRequestRenameModel={onRequestRenameModel}
        onRequestDeleteModel={onRequestDeleteModel}
      />
      <ModelActionDialog
        dialog={modelActionDialog}
        busy={busy}
        onCancel={onCancelModelAction}
        onConfirm={onConfirmModelAction}
      />
    </>
  );
}
