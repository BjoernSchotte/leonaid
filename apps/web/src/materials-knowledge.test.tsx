import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  type CurrentIdentityResponse,
  type LeonAidApiClient,
} from "@leonaid/api-client";
import { resetCommandPaletteState } from "@leonaid/features";
import { HotkeyProvider, ToastProvider } from "@leonaid/ui";

import { KnowledgeEditorPage } from "../../../packages/features/src/knowledge/editor";
import { KnowledgePage } from "../../../packages/features/src/knowledge/knowledge";
import {
  fileIcon,
  formatSize,
  MaterialsPage,
} from "../../../packages/features/src/materials/materials";
import { installDialogPolyfill } from "../../../packages/ui/src/test-utils/dialog-polyfill";

const me = "00000000-0000-4000-8000-0000000000aa";
const other = "00000000-0000-4000-8000-0000000000bb";
const identity = {
  userId: me,
  displayName: "Klara Admin",
  globalRoles: [],
  actionMemberships: [],
  navigation: [],
} as unknown as CurrentIdentityResponse;

beforeAll(() => {
  installDialogPolyfill();
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
  Element.prototype.scrollIntoView ??= () => {};
  window.matchMedia ??= ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener() {},
    removeEventListener() {},
    addListener() {},
    removeListener() {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
  // jsdom has no layout: Tiptap asks for client rects.
  document.elementFromPoint ??= () => null;
  Range.prototype.getClientRects ??= () =>
    ({
      length: 0,
      item: () => null,
      [Symbol.iterator]: [][Symbol.iterator],
    }) as unknown as DOMRectList;
  Range.prototype.getBoundingClientRect ??= () => new DOMRect();
});

afterEach(() => {
  resetCommandPaletteState();
  vi.restoreAllMocks();
});

function wrap(children: ReactNode, path: string) {
  window.history.replaceState(null, "", path);
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <HotkeyProvider>{children}</HotkeyProvider>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

function press(key: string) {
  act(() => {
    (document.activeElement ?? document.body).dispatchEvent(
      new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true }),
    );
  });
}

const contexts = {
  listTaskActionContexts: vi.fn(async () => ({ items: [], nextOffset: null })),
};

describe("material helpers", () => {
  it("formats sizes and picks icons as the prototype does", () => {
    expect(formatSize(512)).toBe("1 KB");
    expect(formatSize(3 * 1024 * 1024 + 200 * 1024)).toBe("3,2 MB");
    expect(fileIcon("plan.xlsx").displayName).toBe(
      fileIcon("a.csv").displayName,
    );
    expect(fileIcon("a.zip")).not.toBe(fileIcon("a.pdf"));
  });
});

describe("materials page", () => {
  function materialsClient() {
    return {
      ...contexts,
      listMaterials: vi.fn(async () => ({
        items: [
          {
            id: "m1",
            title: "Flyer Adventskalender",
            actionId: null,
            currentVersion: 2,
            ownerUserId: me,
            revision: 3,
          },
          {
            id: "m2",
            title: "Tourenplan",
            actionId: "a1",
            currentVersion: 1,
            ownerUserId: other,
            revision: 1,
          },
        ],
        nextOffset: null,
      })),
      getMaterialVersion: vi.fn(async (id: string, version: number) => ({
        materialId: id,
        version,
        filename: version === 2 ? "flyer-v2.pdf" : "flyer.pdf",
        mediaType: "application/pdf",
        sha256: "x",
        sizeBytes: 2 * 1024 * 1024,
      })),
      getMaterialPermissions: vi.fn(async (id: string) => ({
        canEdit: id === "m1",
        canManage: id === "m1",
      })),
      listMaterialMembers: vi.fn(async () => ({
        items: [
          {
            userId: other,
            displayName: "Bernd Binder",
            access: "editor",
            active: true,
          },
        ],
        nextOffset: null,
        accessRevision: 1,
        ownerUserId: me,
      })),
      getMaterial: vi.fn(),
    };
  }

  it("expands the first material with its versions and access", async () => {
    const client = materialsClient();
    wrap(
      <MaterialsPage
        basePath="/admin/materials"
        client={client as unknown as LeonAidApiClient}
        identity={identity}
      />,
      "/admin/materials",
    );
    expect(await screen.findByText("Flyer Adventskalender")).toBeTruthy();
    expect(screen.getByText("2 Dateien")).toBeTruthy();
    expect(await screen.findByText("flyer-v2.pdf")).toBeTruthy();
    expect(await screen.findByText("flyer.pdf")).toBeTruthy();
    expect(screen.getAllByText("2,0 MB")).toHaveLength(2);
    expect(await screen.findByText(/Bearbeiten: Bernd Binder/)).toBeTruthy();
    expect(
      screen.getByRole("button", { name: /^Tourenplan/, expanded: false }),
    ).toBeTruthy();
  });

  it("names the campaign of campaign material (prototype subtitle)", async () => {
    const client = {
      ...materialsClient(),
      listTaskActionContexts: vi.fn(async () => ({
        items: [
          { actionId: "a1", canCreateLists: false, name: "Krapfentaxi 2026" },
        ],
        nextOffset: null,
      })),
    };
    wrap(
      <MaterialsPage
        basePath="/admin/materials"
        client={client as unknown as LeonAidApiClient}
        identity={identity}
      />,
      "/admin/materials",
    );
    const row = await screen.findByRole("button", { name: /^Tourenplan/ });
    await waitFor(() =>
      expect(row.textContent).toContain("Krapfentaxi 2026 · 1 Version"),
    );
    expect(row.textContent).not.toContain("Aktionsmaterial");
    expect(
      screen.getByRole("button", { name: /^Flyer Adventskalender/ })
        .textContent,
    ).toContain("Eigenständig · 2 Versionen");
  });

  it("j moves, u opens the upload for the focused material and checks the size", async () => {
    const client = materialsClient();
    wrap(
      <MaterialsPage
        basePath="/admin/materials"
        client={client as unknown as LeonAidApiClient}
        identity={identity}
      />,
      "/admin/materials",
    );
    await screen.findByText("Tourenplan");
    press("j");
    press("j");
    expect(document.activeElement?.textContent).toContain("Tourenplan");
    press("u");
    const dialog = await screen.findByRole("dialog", {
      name: "Neue Version hochladen",
    });
    // A reader of m2: no upload, a read-only note instead.
    expect(
      await within(dialog).findByText(/keine neue Version hochladen/),
    ).toBeTruthy();
    expect(
      within(dialog).queryByRole("button", { name: /Hochladen/ }),
    ).toBeNull();
    fireEvent.click(within(dialog).getByRole("button", { name: "Abbrechen" }));

    press("k");
    press("u");
    const own = await screen.findByRole("dialog", {
      name: "Neue Version hochladen",
    });
    const big = new File(["x"], "gross.pdf");
    Object.defineProperty(big, "size", { value: 30 * 1024 * 1024 });
    fireEvent.change(within(own).getByLabelText(/Datei/), {
      target: { files: [big] },
    });
    expect(
      within(own).getByText(
        /Die Datei ist 30,0 MB groß\. Erlaubt sind höchstens 25 MiB/,
      ),
    ).toBeTruthy();
    expect(
      (
        within(own).getByRole("button", {
          name: /Hochladen/,
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    // A chosen file is a draft: Abbrechen asks first.
    fireEvent.click(within(own).getByRole("button", { name: "Abbrechen" }));
    const question = await screen.findByRole("alertdialog", {
      name: "Entwurf verwerfen?",
    });
    fireEvent.click(
      within(question).getByRole("button", { name: "Weiter bearbeiten" }),
    );
    await act(async () => {});
    expect(
      screen.getByRole("dialog", { name: "Neue Version hochladen" }),
    ).toBeTruthy();
  });

  it("speaks with du in the app", async () => {
    const client = materialsClient();
    client.listMaterials.mockResolvedValue({ items: [], nextOffset: null });
    wrap(
      <MaterialsPage
        basePath="/app/materials"
        client={client as unknown as LeonAidApiClient}
        identity={identity}
        surface="pwa"
      />,
      "/app/materials?create=material",
    );
    expect(await screen.findByText("Noch kein Material")).toBeTruthy();
    const dialog = await screen.findByRole("dialog", {
      name: "Material hochladen",
    });
    expect(
      within(dialog).getByText(
        "Das neue Material ist zunächst nur für dich sichtbar.",
      ),
    ).toBeTruthy();
  });
});

describe("knowledge", () => {
  function knowledgeClient(
    content: unknown = {
      type: "doc",
      content: [
        {
          type: "paragraph",
          content: [{ type: "text", text: "Treffpunkt 06:15 Uhr." }],
        },
      ],
    },
  ) {
    return {
      ...contexts,
      listKnowledgePages: vi.fn(async () => ({
        items: [
          {
            id: "p1",
            title: "So läuft der Liefertag",
            actionId: null,
            ownerUserId: me,
            revision: 7,
          },
        ],
        nextOffset: null,
      })),
      getKnowledgePage: vi.fn(async () => ({
        id: "p1",
        title: "So läuft der Liefertag",
        actionId: null,
        ownerUserId: me,
        revision: 7,
        content,
      })),
      getKnowledgePagePermissions: vi.fn(async () => ({
        canEdit: true,
        canManage: false,
      })),
      updateKnowledgePage: vi.fn(),
      createKnowledgePage: vi.fn(),
    };
  }

  it("lists pages with their context and revision", async () => {
    const client = knowledgeClient();
    wrap(
      <KnowledgePage
        basePath="/admin/knowledge"
        client={client as unknown as LeonAidApiClient}
        identity={identity}
      />,
      "/admin/knowledge",
    );
    const link = await screen.findByRole("link", {
      name: /So läuft der Liefertag/,
    });
    expect(link.getAttribute("href")).toBe("/admin/knowledge/p1");
    expect(link.textContent).toContain("Eigenständig");
    expect(link.textContent).toContain("Fassung 7");
    fireEvent.click(screen.getByRole("button", { name: "Seite anlegen" }));
    expect(
      await screen.findByRole("dialog", { name: "Neue Seite" }),
    ).toBeTruthy();
  });

  it("reads first, edits with e, and asks before a draft is dropped", async () => {
    const client = knowledgeClient();
    wrap(
      <KnowledgeEditorPage
        basePath="/admin/knowledge"
        client={client as unknown as LeonAidApiClient}
        identity={identity}
        pageId="p1"
      />,
      "/admin/knowledge/p1",
    );
    const editor = await screen.findByRole("textbox", { name: "Seiteninhalt" });
    expect(editor.getAttribute("contenteditable")).toBe("false");
    expect(
      screen.getByText(/Fassung 7/, { selector: ".page-sub" }),
    ).toBeTruthy();
    press("e");
    await act(async () => {});
    expect(editor.getAttribute("contenteditable")).toBe("true");
    fireEvent.change(screen.getByLabelText("Seitentitel"), {
      target: { value: "Liefertag neu" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Abbrechen" }));
    const question = await screen.findByRole("alertdialog", {
      name: "Entwurf verwerfen?",
    });
    fireEvent.click(
      within(question).getByRole("button", { name: "Weiter bearbeiten" }),
    );
    await act(async () => {});
    expect(
      (screen.getByLabelText("Seitentitel") as HTMLInputElement).value,
    ).toBe("Liefertag neu");
    fireEvent.click(screen.getByRole("button", { name: "Abbrechen" }));
    fireEvent.click(
      within(
        await screen.findByRole("alertdialog", { name: "Entwurf verwerfen?" }),
      ).getByRole("button", { name: "Verwerfen" }),
    );
    await act(async () => {});
    expect(screen.queryByLabelText("Seitentitel")).toBeNull();
    expect(editor.getAttribute("contenteditable")).toBe("false");
  });

  it("keeps e off while the task panel is open", async () => {
    const client = knowledgeClient();
    wrap(
      <KnowledgeEditorPage
        basePath="/admin/knowledge"
        client={client as unknown as LeonAidApiClient}
        identity={identity}
        pageId="p1"
      />,
      "/admin/knowledge/p1",
    );
    const editor = await screen.findByRole("textbox", { name: "Seiteninhalt" });
    fireEvent.click(
      screen.getByRole("button", { name: "Aufgabe aus dieser Seite" }),
    );
    (document.activeElement as HTMLElement | null)?.blur();
    press("e");
    await act(async () => {});
    // Editing would show the title field (the editor itself stays locked
    // while the panel is open).
    expect(screen.queryByLabelText("Seitentitel")).toBeNull();
    expect(editor.getAttribute("contenteditable")).toBe("false");
  });

  it("closes the link form with Esc and stays in editing", async () => {
    const client = knowledgeClient();
    wrap(
      <KnowledgeEditorPage
        basePath="/admin/knowledge"
        client={client as unknown as LeonAidApiClient}
        identity={identity}
        pageId="p1"
      />,
      "/admin/knowledge/p1",
    );
    const editor = await screen.findByRole("textbox", { name: "Seiteninhalt" });
    press("e");
    await act(async () => {});
    expect(editor.getAttribute("contenteditable")).toBe("true");
    fireEvent.click(
      screen.getAllByRole("button", { name: "Link bearbeiten" })[0]!,
    );
    const field = await screen.findByLabelText("Link-Adresse");
    field.focus();
    press("Escape");
    await act(async () => {});
    expect(screen.queryByLabelText("Link-Adresse")).toBeNull();
    expect(editor.getAttribute("contenteditable")).toBe("true");
  });

  it("offers both fassungen after a conflict", async () => {
    const client = knowledgeClient();
    client.updateKnowledgePage
      .mockRejectedValueOnce(
        new ApiError(409, { message: "conflict" } as never),
      )
      .mockResolvedValueOnce({
        id: "p1",
        title: "Liefertag neu",
        actionId: null,
        ownerUserId: me,
        revision: 9,
        content: { type: "doc", content: [] },
      });
    wrap(
      <KnowledgeEditorPage
        basePath="/admin/knowledge"
        client={client as unknown as LeonAidApiClient}
        identity={identity}
        pageId="p1"
      />,
      "/admin/knowledge/p1?edit",
    );
    await screen.findByRole("textbox", { name: "Seiteninhalt" });
    expect(window.location.search).toBe("");
    fireEvent.change(screen.getByLabelText("Seitentitel"), {
      target: { value: "Liefertag neu" },
    });
    client.getKnowledgePage.mockResolvedValueOnce({
      id: "p1",
      title: "Liefertag",
      actionId: null,
      ownerUserId: me,
      revision: 8,
      content: { type: "doc", content: [] },
    });
    fireEvent.click(screen.getByRole("button", { name: /Speichern/ }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain(
      "Die Seite wurde inzwischen geändert (Fassung 8).",
    );
    fireEvent.click(
      within(alert).getByRole("button", { name: "Meine Fassung behalten" }),
    );
    await act(async () => {});
    expect(client.updateKnowledgePage).toHaveBeenLastCalledWith(
      "p1",
      expect.objectContaining({ expectedRevision: 8, title: "Liefertag neu" }),
    );
    expect(await screen.findByText("Gespeichert.")).toBeTruthy();
  });

  it("keeps the editor and its draft when a background check fails", async () => {
    const client = knowledgeClient();
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    window.history.replaceState(null, "", "/admin/knowledge/p1?edit");
    render(
      <QueryClientProvider client={queryClient}>
        <ToastProvider>
          <HotkeyProvider>
            <KnowledgeEditorPage
              basePath="/admin/knowledge"
              client={client as unknown as LeonAidApiClient}
              identity={identity}
              pageId="p1"
            />
          </HotkeyProvider>
        </ToastProvider>
      </QueryClientProvider>,
    );
    await screen.findByRole("textbox", { name: "Seiteninhalt" });
    fireEvent.change(screen.getByLabelText("Seitentitel"), {
      target: { value: "Liefertag Entwurf" },
    });
    client.getKnowledgePagePermissions.mockRejectedValueOnce(
      new Error("network"),
    );
    await act(async () => {
      await queryClient.refetchQueries({
        queryKey: ["knowledge-permissions", "p1"],
      });
    });
    expect(
      await screen.findByText(/ließ sich gerade nicht prüfen/),
    ).toBeTruthy();
    // Still mounted with the typed draft; saving waits for the checks.
    expect(
      (screen.getByLabelText("Seitentitel") as HTMLInputElement).value,
    ).toBe("Liefertag Entwurf");
    expect(
      (screen.getByRole("button", { name: /Speichern/ }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    expect(screen.queryByText(/Sie können diese Seite lesen/)).toBeNull();
  });

  it("asks before taking the other fassung over a draft", async () => {
    const client = knowledgeClient();
    client.updateKnowledgePage.mockRejectedValueOnce(
      new ApiError(409, { message: "conflict" } as never),
    );
    wrap(
      <KnowledgeEditorPage
        basePath="/admin/knowledge"
        client={client as unknown as LeonAidApiClient}
        identity={identity}
        pageId="p1"
      />,
      "/admin/knowledge/p1?edit",
    );
    await screen.findByRole("textbox", { name: "Seiteninhalt" });
    fireEvent.change(screen.getByLabelText("Seitentitel"), {
      target: { value: "Liefertag neu" },
    });
    client.getKnowledgePage.mockResolvedValueOnce({
      id: "p1",
      title: "Liefertag anders",
      actionId: null,
      ownerUserId: me,
      revision: 8,
      content: {
        type: "doc",
        content: [
          { type: "paragraph", content: [{ type: "text", text: "Andere" }] },
        ],
      },
    });
    fireEvent.click(screen.getByRole("button", { name: /Speichern/ }));
    const alert = await screen.findByRole("alert");
    fireEvent.click(
      within(alert).getByRole("button", { name: "Andere übernehmen" }),
    );
    const question = await screen.findByRole("alertdialog", {
      name: "Entwurf verwerfen?",
    });
    fireEvent.click(
      within(question).getByRole("button", { name: "Weiter bearbeiten" }),
    );
    await act(async () => {});
    expect(
      (screen.getByLabelText("Seitentitel") as HTMLInputElement).value,
    ).toBe("Liefertag neu");
    fireEvent.click(
      within(alert).getByRole("button", { name: "Andere übernehmen" }),
    );
    fireEvent.click(
      within(
        await screen.findByRole("alertdialog", { name: "Entwurf verwerfen?" }),
      ).getByRole("button", { name: "Verwerfen" }),
    );
    await act(async () => {});
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(
      "Liefertag anders",
    );
  });

  it("shows readers a read-only note and no edit", async () => {
    const client = knowledgeClient();
    client.getKnowledgePagePermissions.mockResolvedValue({
      canEdit: false,
      canManage: false,
    });
    wrap(
      <KnowledgeEditorPage
        basePath="/app/knowledge"
        client={client as unknown as LeonAidApiClient}
        identity={identity}
        pageId="p1"
        surface="pwa"
      />,
      "/app/knowledge/p1",
    );
    expect(await screen.findByText(/Du kannst diese Seite lesen/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Bearbeiten/ })).toBeNull();
  });
});
