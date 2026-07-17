import type { CanvasNode } from "./contracts";

export type SaveState =
  | { status: "saved"; savedAt: Date | null }
  | { status: "dirty"; savedAt: Date | null }
  | { status: "saving"; savedAt: Date | null }
  | { status: "error"; savedAt: Date | null; error: unknown };

interface AutosaveQueueOptions {
  save: (node: CanvasNode) => Promise<CanvasNode>;
  onSaved: (node: CanvasNode) => void;
  onStateChange: (state: SaveState) => void;
  debounceMs?: number;
}

/**
 * Serializes all graph writes. A second edit made while a node is saving is
 * rebased onto the revision returned by the first write before it is sent.
 */
export class AutosaveQueue {
  private readonly dirty = new Map<string, CanvasNode>();
  private readonly saveNode: AutosaveQueueOptions["save"];
  private readonly onSaved: AutosaveQueueOptions["onSaved"];
  private readonly onStateChange: AutosaveQueueOptions["onStateChange"];
  private readonly debounceMs: number;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private currentFlush: Promise<boolean> | null = null;
  private savedAt: Date | null = null;
  private disposed = false;

  constructor(options: AutosaveQueueOptions) {
    this.saveNode = options.save;
    this.onSaved = options.onSaved;
    this.onStateChange = options.onStateChange;
    this.debounceMs = options.debounceMs ?? 650;
  }

  mark(node: CanvasNode): void {
    if (this.disposed || node.id.startsWith("temp-")) return;
    this.dirty.set(node.id, node);
    this.onStateChange({ status: "dirty", savedAt: this.savedAt });
    this.schedule();
  }

  private schedule(): void {
    if (this.timer) clearTimeout(this.timer);
    this.timer = setTimeout(() => {
      this.timer = null;
      void this.flush();
    }, this.debounceMs);
  }

  async flush(): Promise<void> {
    if (this.disposed) return;
    if (this.timer) {
      clearTimeout(this.timer);
      this.timer = null;
    }

    if (this.currentFlush) {
      const failed = await this.currentFlush;
      if (!failed && this.dirty.size > 0) await this.flush();
      return;
    }
    if (this.dirty.size === 0) return;

    const pending = [...this.dirty.values()];
    pending.forEach((node) => this.dirty.delete(node.id));
    this.onStateChange({ status: "saving", savedAt: this.savedAt });

    this.currentFlush = this.persistBatch(pending);
    const failed = await this.currentFlush;
    this.currentFlush = null;

    if (failed) return;
    if (this.dirty.size > 0) {
      await this.flush();
      return;
    }

    this.savedAt = new Date();
    this.onStateChange({ status: "saved", savedAt: this.savedAt });
  }

  private async persistBatch(pending: CanvasNode[]): Promise<boolean> {
    let firstError: unknown;

    for (const node of pending) {
      try {
        const saved = await this.saveNode(node);
        const newer = this.dirty.get(node.id);
        if (newer && newer.revision === node.revision) {
          this.dirty.set(node.id, {
            ...newer,
            revision: saved.revision,
            updatedAt: saved.updatedAt,
          });
        }
        this.onSaved(saved);
      } catch (error) {
        if (!this.dirty.has(node.id)) this.dirty.set(node.id, node);
        firstError ??= error;
      }
    }

    if (firstError) {
      this.onStateChange({ status: "error", savedAt: this.savedAt, error: firstError });
      return true;
    }
    return false;
  }

  retry(): void {
    if (this.dirty.size === 0) return;
    void this.flush();
  }

  dispose(): void {
    this.disposed = true;
    if (this.timer) clearTimeout(this.timer);
  }
}
