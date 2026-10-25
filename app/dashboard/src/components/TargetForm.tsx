import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { post } from "../api/client";
import { useResource } from "../api/queries";
import type { Profiles, TargetImages } from "../api/types";
import { ErrorMessage, FieldError } from "./common";

export default function TargetForm({
  projectId,
  onCreated,
}: {
  projectId: string;
  onCreated?: (id: string) => void;
}) {
  const [kind, setKind] = useState<"docker" | "website">("docker");
  const images = useResource<TargetImages>("/target-images", kind === "docker");
  const profiles = useResource<Profiles>("/runtime/profiles");
  const [launchProfile, setLaunchProfile] = useState("");
  const [networkProfile, setNetworkProfile] = useState("");
  const [trustProfile, setTrustProfile] = useState("");
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
        kind,
        image: kind === "docker" ? image.trim() : null,
        launch_profile: kind === "docker" ? launchProfile || null : null,
        network_profile: kind === "website" ? networkProfile || null : null,
        trust_profile: trustProfile || null,
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
      <label>Assessment source<select value={kind} onChange={e => setKind(e.target.value as "docker" | "website")}>
        <option value="docker">Docker</option><option value="website">Existing website</option>
      </select></label>
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
      {kind === "docker" && <label>
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
      </label>}
      {kind === "docker" && <label>Launch profile<select value={launchProfile} onChange={e => setLaunchProfile(e.target.value)}>
        <option value="">Self-contained application</option>{Object.keys(profiles.data?.launches ?? {}).map(name => <option key={name}>{name}</option>)}
      </select></label>}
      {kind === "website" && <label>Private staging permission<select value={networkProfile} onChange={e => setNetworkProfile(e.target.value)}>
        <option value="">Public destinations only</option>{Object.keys(profiles.data?.networks ?? {}).map(name => <option key={name}>{name}</option>)}
      </select></label>}
      <label>Certificate trust<select value={trustProfile} onChange={e => setTrustProfile(e.target.value)}>
        <option value="">System trust</option>{(profiles.data?.trusts ?? []).map(name => <option key={name}>{name}</option>)}
      </select></label>
      <p className="hint">
        {kind === "docker" ? "Docker checks inspect a disposable instance of this image." : "Website checks request the existing deployment."} The registered URL defines which response URLs you can assess.
      </p>
      {kind === "docker" && <button type="button" className="subtle" disabled={images.isFetching}
        onClick={() => { void images.refetch(); }}>
        Refresh images
      </button>}
      {kind === "docker" && <ErrorMessage error={images.error} retry={images.refetch} />}
      <ErrorMessage error={create.error} />
      <button
        type="submit"
        disabled={create.isPending || (kind === "docker" && !image.trim()) || !name.trim() || !url.trim()}
      >
        {create.isPending ? "Registering…" : "Register target"}
      </button>
    </form>
  );
}
