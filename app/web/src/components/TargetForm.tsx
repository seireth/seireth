import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { post } from "../api/client";
import { useResource } from "../api/queries";
import type { Runtime } from "../api/types";
import { ErrorMessage, FieldError } from "./common";

export default function TargetForm({
  projectId,
  onCreated,
}: {
  projectId: string;
  onCreated?: (id: string) => void;
}) {
  const runtime = useResource<Runtime>("/runtime");
  const client = useQueryClient();
  const [name, setName] = useState("");
  const [url, setUrl] = useState("http://demo-target:8080/");
  const [image, setImage] = useState("");
  const create = useMutation({
    mutationFn: () =>
      post<{ id: string }>("/targets", {
        project_id: projectId,
        name: name.trim(),
        url,
        image: image || runtime.data?.default_target_image,
      }),
    onSuccess: ({ id }) => {
      void client.invalidateQueries({
        queryKey: [`/projects/${projectId}/targets`],
      });
      setName("");
      onCreated?.(id);
    },
  });
  return (
    <form
      className="form-grid"
      onSubmit={(e) => {
        e.preventDefault();
        if (!create.isPending) create.mutate();
      }}
    >
      <label>
        Target name
        <input
          required
          maxLength={200}
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <FieldError error={create.error} name="name" />
      </label>
      <label>
        Registered URL
        <input
          required
          type="url"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
        />
        <FieldError error={create.error} name="url" />
      </label>
      <label>
        Allowed image
        <select
          required
          value={image || runtime.data?.default_target_image || ""}
          onChange={(e) => setImage(e.target.value)}
        >
          {runtime.data?.allowed_target_images.map((i) => (
            <option key={i}>{i}</option>
          ))}
        </select>
        <FieldError error={create.error} name="image" />
      </label>
      <p className="hint">
        Docker checks inspect a disposable instance of this image. The
        registered URL defines its authorization boundary.
      </p>
      <ErrorMessage
        error={runtime.error}
        retry={() => {
          void runtime.refetch();
        }}
      />
      <ErrorMessage error={create.error} />
      <button
        type="submit"
        disabled={create.isPending || !runtime.data || !name.trim()}
      >
        {create.isPending ? "Registering…" : "Register target"}
      </button>
    </form>
  );
}
