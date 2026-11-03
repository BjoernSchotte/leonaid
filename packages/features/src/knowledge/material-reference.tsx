import { useQuery, useMutation } from "@tanstack/react-query";
import { Node } from "@tiptap/core";
import {
  NodeViewWrapper,
  ReactNodeViewRenderer,
  type NodeViewProps,
} from "@tiptap/react";
import type { LeonAidApiClient } from "@leonaid/api-client";
import { Button, StatusMessage } from "@leonaid/ui";
import { downloadMaterial } from "../materials/download";

export function materialReference(client: LeonAidApiClient) {
  function Reference({ node }: NodeViewProps) {
    const id = String(node.attrs.materialId);
    const version = Number(node.attrs.version);
    const metadata = useQuery({
      queryKey: ["material-version", id, version],
      queryFn: () => client.getMaterialVersion(id, version),
      retry: false,
      refetchInterval: 30000,
    });
    const download = useMutation({
      mutationFn: () => downloadMaterial(client, metadata.data!),
    });
    return (
      <NodeViewWrapper
        className="knowledge-task-reference"
        contentEditable={false}
      >
        {metadata.error ? (
          <span>Material nicht verfügbar</span>
        ) : metadata.data ? (
          <>
            <p>
              {metadata.data.filename} · Dateiversion {version}
            </p>
            <Button
              variant="secondary"
              disabled={download.isPending}
              onClick={() => download.mutate()}
            >
              {download.isPending
                ? "Download wird vorbereitet …"
                : "Verknüpfte Dateiversion herunterladen"}
            </Button>
          </>
        ) : (
          <span role="status">Material wird geladen …</span>
        )}
        {download.error && (
          <StatusMessage tone="error">
            Download fehlgeschlagen. Prüfe deinen Zugriff und versuche es
            erneut.
          </StatusMessage>
        )}
      </NodeViewWrapper>
    );
  }
  return Node.create({
    name: "materialReference",
    group: "block",
    atom: true,
    addAttributes: () => ({
      materialId: { default: null },
      version: { default: null },
    }),
    parseHTML: () => [
      {
        tag: "div[data-material-reference]",
        getAttrs: (element) => ({
          materialId: element.getAttribute("data-material-reference"),
          version: Number(element.getAttribute("data-material-version")),
        }),
      },
    ],
    renderHTML: ({ node }) => [
      "div",
      {
        "data-material-reference": node.attrs.materialId,
        "data-material-version": node.attrs.version,
      },
      "Material",
    ],
    addNodeView: () => ReactNodeViewRenderer(Reference),
  });
}
