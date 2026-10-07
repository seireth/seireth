import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { post } from "../api/client";
import { useResource } from "../api/queries";
import type { TargetImages } from "../api/types";
import { ErrorMessage, FieldError } from "./common";

export default function TargetForm({
  projectId,
  onCreated,
}: {
  projectId: string;
  onCreated?: (id: string) => void;
}) {
  const images = useResource<TargetImages>("/target-images");
  const client = useQueryClient();
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [image, setImage] = useState("");
  const create = useMutation({
    mutationFn: () =>
      post<{ id: string }>("/targets", {
        project_id: projectId,
        name: name.trim(),
        url,
        image: image.trim(),
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
          placeholder="http://your-app:8080/"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
        />
        <FieldError error={create.error} name="url" />
      </label>
      <label>
        Docker image
        <input
          required
          maxLength={300}
          list="target-images"
          placeholder="repository:tag"
          value={image}
          onChange={(e) => setImage(e.target.value)}
        />
        <datalist id="target-images">
          {images.data?.items.map((i) => (
            <option key={i.image} value={i.image} />
          ))}
        </datalist>
        <FieldError error={create.error} name="image" />
      </label>
      <p className="hint">
        Docker checks inspect a disposable instance of this image. The
        registered URL defines which response URLs you can assess.
      </p>
      <button type="button" className="subtle" disabled={images.isFetching}
        onClick={() => { void images.refetch(); }}>
        Refresh images
      </button>
      <ErrorMessage error={images.error} retry={images.refetch} />
      <ErrorMessage error={create.error} />
      <button
        type="submit"
        disabled={create.isPending || !image.trim() || !name.trim() || !url.trim()}
      >
        {create.isPending ? "Registering…" : "Register target"}
      </button>
    </form>
  );
}
