"use client";

import { useCallback, useState, useRef } from "react";

interface UploadDropzoneProps {
  onUpload?: (file: File) => void;
  disabled?: boolean;
  isUploading?: boolean;
}

export default function UploadDropzone({
  onUpload,
  disabled = false,
  isUploading = false,
}: UploadDropzoneProps) {
  const [file, setFile] = useState<File | null>(null);
  const [isDragOver, setIsDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleFile = useCallback(
    (f: File) => {
      if (disabled || isUploading) return;
      if (f.type === "application/pdf" || f.name.endsWith(".pdf")) {
        setFile(f);
      }
    },
    [disabled, isUploading],
  );

  const handleDrop = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      setIsDragOver(false);
      if (disabled || isUploading) return;
      const dropped = e.dataTransfer.files[0];
      if (dropped) handleFile(dropped);
    },
    [handleFile, disabled, isUploading],
  );

  const handleDragOver = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      if (!disabled && !isUploading) setIsDragOver(true);
    },
    [disabled, isUploading],
  );

  const handleDragLeave = useCallback(() => {
    setIsDragOver(false);
  }, []);

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const selected = e.target.files?.[0];
      if (selected) handleFile(selected);
    },
    [handleFile],
  );

  const handleUploadClick = useCallback(() => {
    if (file && onUpload && !disabled && !isUploading) {
      onUpload(file);
    }
  }, [file, onUpload, disabled, isUploading]);

  const reset = useCallback(() => {
    setFile(null);
    if (inputRef.current) inputRef.current.value = "";
  }, []);

  return (
    <div className="max-w-xl">
      <div
        onDrop={handleDrop}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onClick={() => {
          if (!disabled && !isUploading) inputRef.current?.click();
        }}
        className={`
          border-2 border-dashed rounded-lg p-12 text-center transition-colors
          ${disabled || isUploading ? "cursor-not-allowed opacity-60" : "cursor-pointer"}
          ${
            isDragOver
              ? "border-blue-500 bg-blue-50"
              : "border-slate-300 hover:border-slate-400"
          }
        `}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".pdf"
          onChange={handleChange}
          className="hidden"
          disabled={disabled || isUploading}
        />

        {isUploading ? (
          <div className="flex flex-col items-center gap-3">
            <svg
              className="animate-spin h-8 w-8 text-blue-600"
              xmlns="http://www.w3.org/2000/svg"
              fill="none"
              viewBox="0 0 24 24"
            >
              <circle
                className="opacity-25"
                cx="12"
                cy="12"
                r="10"
                stroke="currentColor"
                strokeWidth="4"
              />
              <path
                className="opacity-75"
                fill="currentColor"
                d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
              />
            </svg>
            <p className="text-sm text-blue-600 font-medium">
              Processing PDF...
            </p>
          </div>
        ) : file ? (
          <div>
            <div className="text-blue-600 text-lg mb-1 font-mono">PDF</div>
            <p className="text-sm text-slate-700 font-medium">{file.name}</p>
            <p className="text-xs text-slate-400 mt-1">
              {(file.size / 1024).toFixed(1)} KB
            </p>
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                reset();
              }}
              className="mt-2 text-xs text-slate-400 hover:text-red-500 underline transition-colors"
            >
              Remove
            </button>
          </div>
        ) : (
          <div>
            <div className="text-3xl text-slate-300 mb-3">&uarr;</div>
            <p className="text-sm text-slate-500">
              Drop your bank statement PDF here
            </p>
            <p className="text-xs text-slate-400 mt-1">or click to browse</p>
          </div>
        )}
      </div>

      {!isUploading && (
        <button
          onClick={handleUploadClick}
          disabled={!file || disabled}
          className={`
            mt-4 w-full py-2.5 rounded-lg text-sm font-medium transition-colors
            ${
              file && !disabled
                ? "bg-blue-600 text-white hover:bg-blue-700"
                : "bg-slate-100 text-slate-400 cursor-not-allowed"
            }
          `}
        >
          Upload and Learn Format
        </button>
      )}
    </div>
  );
}
