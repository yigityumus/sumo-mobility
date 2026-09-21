import { GripVertical } from "lucide-react";
import * as ResizablePrimitive from "react-resizable-panels";
import { cn } from "../../lib/utils";

function ResizablePanelGroup({ className, ...props }: React.ComponentProps<typeof ResizablePrimitive.Group>) {
  return <ResizablePrimitive.Group className={cn("flex h-full w-full", className)} {...props} />;
}
const ResizablePanel = ResizablePrimitive.Panel;
function ResizableHandle({ withHandle, className, ...props }: React.ComponentProps<typeof ResizablePrimitive.Separator> & { withHandle?: boolean }) {
  return <ResizablePrimitive.Separator className={cn("relative z-30 flex w-px items-center justify-center bg-border after:absolute after:inset-y-0 after:left-1/2 after:w-3 after:-translate-x-1/2 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring data-[resize-handle-active]:bg-primary aria-[orientation=horizontal]:h-px aria-[orientation=horizontal]:w-full aria-[orientation=horizontal]:after:left-0 aria-[orientation=horizontal]:after:h-3 aria-[orientation=horizontal]:after:w-full aria-[orientation=horizontal]:after:-translate-y-1/2 aria-[orientation=horizontal]:after:translate-x-0", className)} {...props}>
    {withHandle && <div className="z-10 flex h-6 w-4 items-center justify-center rounded-sm border bg-border"><GripVertical className="size-3" /></div>}
  </ResizablePrimitive.Separator>;
}
export { ResizablePanelGroup, ResizablePanel, ResizableHandle };
