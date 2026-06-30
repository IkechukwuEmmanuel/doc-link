import React, { useState, useEffect } from 'react';

const CollabEditor: React.FC = () => {
  const [peers, setPeers] = useState<Array<{ id: string; name: string }>[]);
  const [isEditing, setIsEditing] = useState(false);

  useEffect(() => {
    const fetchPeers = async () => {
      const response = await fetch('/api/peers');
      const data = await response.json();
      setPeers(data);
    };
    fetchPeers();
  }, []);

  const handlePeerJoin = (peer) => {
    setPeers(prev => [...prev, peer]);
  };

  return (
    <div className="editor-container">
      {isEditing ? (
        <div className="editor-warning">
          Editing peers...
        </div>
      ) : (
        <div className="editor-content">
          {peers.map(peer => (
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
