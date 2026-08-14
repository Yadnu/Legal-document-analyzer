"use client";

import { useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Upload, Loader2 } from "lucide-react";
import {
  requestPresignedUpload,
  putFileToS3,
  confirmUpload,
  getDocument,
} from "@/lib/api";

const ACCEPTED_TYPES = [
  "application/pdf",
  "application/msword",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
];

const MAX_SIZE_BYTES = 52_428_800; // 50 MB

type Stage = "idle" | "presigning" | "uploading" | "confirming" | "polling";

export function UploadButton() {
  const inputRef = useRef<HTMLInputElement>(null);
  const queryClient = useQueryClient();
  const [stage, setStage] = useState<Stage>("idle");
  const [error, setError] = useState<string | null>(null);

  const upload = useMutation({
    mutationFn: async (file: File) => {
      setStage("presigning");
      const { document_id, upload_url } = await requestPresignedUpload({
        filename: file.name,
        content_type: file.type,
        size_bytes: file.size,
      });

      setStage("uploading");
      await putFileToS3(upload_url, file);

      setStage("confirming");
      await confirmUpload(document_id);

      // Poll until the status leaves "processing"
      setStage("polling");
      let attempts = 0;
      while (attempts < 30) {
        await new Promise((r) => setTimeout(r, 2000));
        const doc = await getDocument(document_id);
        if (doc.status !== "processing") break;
        attempts++;
      }
    },
    onSuccess: () => {
      setStage("idle");
      setError(null);
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
    },
    onError: (err: Error) => {
      setStage("idle");
      setError(err.message);
    },
  });

  const isbusy = stage !== "idle";

  function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    e.target.value = "";
    setError(null);

    if (!ACCEPTED_TYPES.includes(file.type)) {
      setError("Only PDF and Word documents are accepted.");
      return;
    }
    if (file.size > MAX_SIZE_BYTES) {
      setError("File exceeds 50 MB limit.");
      return;
    }
    upload.mutate(file);
  }

  const stageLabel: Record<Stage, string> = {
    idle: "Upload document",
    presigning: "Preparing…",
    uploading: "Uploading…",
    confirming: "Saving…",
    polling: "Processing…",
  };

  return (
    <div className="flex flex-col items-start gap-2">
      <button
        onClick={() => inputRef.current?.click()}
        disabled={isbusy}
        className="btn-primary"
      >
        {isbusy ? (
          <Loader2 size={16} className="animate-spin" />
        ) : (
          <Upload size={16} />
        )}
        {stageLabel[stage]}
      </button>

      <input
        ref={inputRef}
        type="file"
        accept=".pdf,.doc,.docx"
        className="hidden"
        onChange={handleChange}
      />

      {error && (
        <p className="text-xs text-status-failed font-mono">{error}</p>
      )}
    </div>
  );
}
