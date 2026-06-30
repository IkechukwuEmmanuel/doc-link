import React, { useState, useEffect } from 'react';

type Peer = { id: string; name: string };

const CollabEditor: React.FC = () => {
  const [peers, setPeers] = useState<Peer[]>([]);
  const [isEditing, setIsEditing] = useState<boolean>(false);

  useEffect(() => {
    let mounted = true;
    const fetchPeers = async () => {
      try {
        const response = await fetch('/api/peers');
        if (!response.ok) return;
        const data: Peer[] = await response.json();
        if (mounted) setPeers(data || []);
      } catch {
        // ignore network errors in this lightweight component
      }
    };
    fetchPeers();
    return () => {
      mounted = false;
    };
  }, []);

  const handlePeerJoin = (peer: Peer) => {
    setPeers((prev) => [...prev, peer]);
  };

  return (
    <div className="editor-container">
      {isEditing ? (
        <div className="editor-warning">Editing peers...</div>
      ) : (
        <div className="editor-content">
          {peers.map((peer) => (
            <div key={peer.id} className="peer-item">
              {peer.name}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default CollabEditor;
