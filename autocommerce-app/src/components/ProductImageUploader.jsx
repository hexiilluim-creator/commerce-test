import React, { useState, useCallback, useRef } from 'react';

/**
 * ProductImageUploader Component
 * Interface drag-and-drop pour uploader jusqu'à 3-5 images par produit
 * Respecte les quotas définis par le plan d'abonnement
 */
export default function ProductImageUploader({ productId, quota = 3, onImagesUpdate }) {
  const [images, setImages] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [dragActive, setDragActive] = useState(false);
  const fileInputRef = useRef(null);

  // Récupérer les images existantes au montage
  React.useEffect(() => {
    fetchImages();
  }, [productId]);

  const fetchImages = async () => {
    try {
      const response = await fetch(`/api/v1/products/${productId}/images`);
      if (response.ok) {
        const data = await response.json();
        setImages(data.images || []);
      }
    } catch (err) {
      console.error('Failed to fetch images:', err);
    }
  };

  // Gestion du drag-and-drop
  const handleDrag = (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragActive(true);
    } else if (e.type === 'dragleave') {
      setDragActive(false);
    }
  };

  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);

    const files = e.dataTransfer.files;
    if (files && files.length > 0) {
      handleFiles(files);
    }
  };

  // Gestion de la sélection de fichiers
  const handleFileSelect = (e) => {
    if (e.target.files && e.target.files.length > 0) {
      handleFiles(e.target.files);
    }
  };

  // Upload des fichiers
  const handleFiles = async (files) => {
    setError(null);
    setLoading(true);

    for (const file of files) {
      // Vérification du quota
      if (images.length >= quota) {
        setError(`Quota atteint (${quota} images max)`);
        break;
      }

      // Vérification du type de fichier
      if (!file.type.startsWith('image/')) {
        setError('Seules les images sont acceptées');
        continue;
      }

      // Vérification de la taille (5 MB)
      if (file.size > 5 * 1024 * 1024) {
        setError('Fichier trop volumineux (max 5 MB)');
        continue;
      }

      try {
        const formData = new FormData();
        formData.append('file', file);

        const response = await fetch(`/api/v1/products/${productId}/images`, {
          method: 'POST',
          body: formData,
        });

        if (!response.ok) {
          const errorData = await response.json();
          setError(errorData.detail || 'Upload échoué');
          continue;
        }

        const result = await response.json();
        setImages((prev) => [...prev, result.url]);

        if (onImagesUpdate) {
          onImagesUpdate([...images, result.url]);
        }
      } catch (err) {
        setError(`Erreur lors de l'upload: ${err.message}`);
      }
    }

    setLoading(false);
  };

  // Suppression d'une image
  const handleDeleteImage = async (index) => {
    try {
      const response = await fetch(
        `/api/v1/products/${productId}/images/${index}`,
        { method: 'DELETE' }
      );

      if (response.ok) {
        const newImages = images.filter((_, i) => i !== index);
        setImages(newImages);

        if (onImagesUpdate) {
          onImagesUpdate(newImages);
        }
      } else {
        setError('Suppression échouée');
      }
    } catch (err) {
      setError(`Erreur lors de la suppression: ${err.message}`);
    }
  };

  const canUploadMore = images.length < quota;

  return (
    <div style={{
      background: 'white',
      borderRadius: '16px',
      padding: '24px',
      border: '1.5px solid #e5e7eb',
    }}>
      {/* Titre */}
      <h3 style={{
        fontSize: '16px',
        fontWeight: '700',
        color: '#0c0c0c',
        marginBottom: '16px',
        display: 'flex',
        alignItems: 'center',
        gap: '8px',
      }}>
        🖼️ Photos du Produit
        <span style={{
          fontSize: '12px',
          fontWeight: '600',
          color: '#6a6a6a',
          background: '#f3f4f6',
          padding: '4px 8px',
          borderRadius: '6px',
        }}>
          {images.length}/{quota}
        </span>
      </h3>

      {/* Zone de drag-and-drop */}
      {canUploadMore && (
        <div
          onDragEnter={handleDrag}
          onDragLeave={handleDrag}
          onDragOver={handleDrag}
          onDrop={handleDrop}
          onClick={() => fileInputRef.current?.click()}
          style={{
            border: dragActive ? '2px dashed #1d4ed8' : '2px dashed #e5e7eb',
            borderRadius: '12px',
            padding: '32px',
            textAlign: 'center',
            cursor: 'pointer',
            background: dragActive ? '#eff6ff' : '#f9fafb',
            transition: 'all 0.2s',
            marginBottom: '20px',
          }}
        >
          <div style={{ fontSize: '32px', marginBottom: '12px' }}>📸</div>
          <p style={{
            fontSize: '14px',
            fontWeight: '600',
            color: '#0c0c0c',
            margin: '0 0 8px',
          }}>
            Glissez vos photos ici
          </p>
          <p style={{
            fontSize: '12px',
            color: '#6a6a6a',
            margin: 0,
          }}>
            ou cliquez pour sélectionner (JPG, PNG, WebP - Max 5 MB)
          </p>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept="image/*"
            onChange={handleFileSelect}
            style={{ display: 'none' }}
          />
        </div>
      )}

      {/* Messages d'erreur */}
      {error && (
        <div style={{
          background: '#fef2f2',
          border: '1px solid #fecaca',
          borderRadius: '8px',
          padding: '12px',
          color: '#dc2626',
          fontSize: '13px',
          marginBottom: '16px',
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
        }}>
          <span>⚠️</span>
          {error}
        </div>
      )}

      {/* Galerie d'images */}
      {images.length > 0 && (
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(100px, 1fr))',
          gap: '12px',
        }}>
          {images.map((imageUrl, index) => (
            <div
              key={index}
              style={{
                position: 'relative',
                borderRadius: '12px',
                overflow: 'hidden',
                border: '1.5px solid #e5e7eb',
                aspectRatio: '1',
                background: '#f3f4f6',
              }}
            >
              <img
                src={imageUrl}
                alt={`Product image ${index + 1}`}
                style={{
                  width: '100%',
                  height: '100%',
                  objectFit: 'cover',
                }}
              />
              {/* Badge index */}
              <div style={{
                position: 'absolute',
                top: '4px',
                left: '4px',
                background: 'rgba(0,0,0,0.7)',
                color: 'white',
                width: '24px',
                height: '24px',
                borderRadius: '50%',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: '11px',
                fontWeight: '700',
              }}>
                {index + 1}
              </div>
              {/* Bouton supprimer */}
              <button
                onClick={() => handleDeleteImage(index)}
                disabled={loading}
                style={{
                  position: 'absolute',
                  top: '4px',
                  right: '4px',
                  background: 'rgba(220, 38, 38, 0.9)',
                  color: 'white',
                  border: 'none',
                  width: '28px',
                  height: '28px',
                  borderRadius: '6px',
                  cursor: loading ? 'not-allowed' : 'pointer',
                  fontSize: '14px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  opacity: loading ? 0.6 : 1,
                  transition: 'all 0.2s',
                }}
                onMouseEnter={(e) => {
                  if (!loading) e.target.style.background = 'rgba(220, 38, 38, 1)';
                }}
                onMouseLeave={(e) => {
                  e.target.style.background = 'rgba(220, 38, 38, 0.9)';
                }}
              >
                ✕
              </button>
            </div>
          ))}
        </div>
      )}

      {/* État vide */}
      {images.length === 0 && !canUploadMore && (
        <div style={{
          textAlign: 'center',
          padding: '20px',
          color: '#6a6a6a',
          fontSize: '13px',
        }}>
          <p>Quota atteint ({quota} images)</p>
          <p style={{ fontSize: '12px', margin: '8px 0 0' }}>
            Supprimez une image pour en ajouter une nouvelle
          </p>
        </div>
      )}

      {/* État de chargement */}
      {loading && (
        <div style={{
          textAlign: 'center',
          padding: '20px',
          color: '#1d4ed8',
          fontSize: '13px',
        }}>
          ⏳ Upload en cours...
        </div>
      )}

      {/* Info quota */}
      <div style={{
        marginTop: '16px',
        padding: '12px',
        background: '#f0fdf4',
        borderRadius: '8px',
        fontSize: '12px',
        color: '#065f46',
        display: 'flex',
        alignItems: 'center',
        gap: '8px',
      }}>
        <span>ℹ️</span>
        <span>
          {canUploadMore
            ? `Vous pouvez ajouter ${quota - images.length} image(s) de plus`
            : `Quota atteint (${quota}/${quota} images)`}
        </span>
      </div>
    </div>
  );
}
