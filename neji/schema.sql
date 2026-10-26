-- Esquema de Neji POS (SQLite).
-- Montos en pesos chilenos como INTEGER (sin decimales).
-- Cantidades como REAL para permitir venta a granel (kg, m, l).
-- Fechas como TEXT 'YYYY-MM-DD HH:MM:SS' en hora local.

CREATE TABLE IF NOT EXISTS config (
    clave TEXT PRIMARY KEY,
    valor TEXT
);

CREATE TABLE IF NOT EXISTS usuarios (
    id            INTEGER PRIMARY KEY,
    usuario       TEXT NOT NULL UNIQUE COLLATE NOCASE,
    nombre        TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    rol           TEXT NOT NULL CHECK (rol IN ('admin', 'cajero')),
    activo        INTEGER NOT NULL DEFAULT 1,
    creado        TEXT NOT NULL,
    nombre_ticket TEXT,              -- cómo aparece en «Atendió:» del ticket (vacío = el nombre)
    permisos      TEXT               -- JSON {permiso: true/false} del cajero (ver auth.PERMISOS)
);

CREATE TABLE IF NOT EXISTS cajas (
    id        INTEGER PRIMARY KEY,
    nombre    TEXT NOT NULL UNIQUE,
    activa    INTEGER NOT NULL DEFAULT 1,
    principal INTEGER NOT NULL DEFAULT 0   -- desde aquí se hace el corte general de todas las cajas
);

CREATE TABLE IF NOT EXISTS departamentos (
    id     INTEGER PRIMARY KEY,
    nombre TEXT NOT NULL UNIQUE COLLATE NOCASE
);

CREATE TABLE IF NOT EXISTS productos (
    id               INTEGER PRIMARY KEY,
    codigo           TEXT NOT NULL UNIQUE,
    descripcion      TEXT NOT NULL,
    departamento_id  INTEGER REFERENCES departamentos(id) ON DELETE SET NULL,
    tipo_venta       TEXT NOT NULL DEFAULT 'unidad' CHECK (tipo_venta IN ('unidad', 'granel')),
    precio_costo     INTEGER NOT NULL DEFAULT 0,
    precio_venta     INTEGER NOT NULL,
    precio_mayoreo   INTEGER,          -- NULL = sin precio de mayoreo
    cantidad_mayoreo REAL,             -- desde esta cantidad se aplica mayoreo solo; NULL = solo con F11
    usa_inventario   INTEGER NOT NULL DEFAULT 1,
    existencia       REAL NOT NULL DEFAULT 0,
    minimo           REAL NOT NULL DEFAULT 0,
    maximo           REAL,
    exento           INTEGER NOT NULL DEFAULT 0,  -- exento de IVA
    proveedor        TEXT,             -- distribuidor / laboratorio
    vencimiento      TEXT,             -- AAAA-MM-DD del lote en venta
    activo           INTEGER NOT NULL DEFAULT 1,
    creado           TEXT NOT NULL,
    actualizado      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_productos_descripcion ON productos(descripcion);
CREATE INDEX IF NOT EXISTS idx_productos_departamento ON productos(departamento_id);

-- Kardex: cada cambio de existencia queda registrado.
CREATE TABLE IF NOT EXISTS movimientos_inventario (
    id                  INTEGER PRIMARY KEY,
    producto_id         INTEGER NOT NULL REFERENCES productos(id) ON DELETE CASCADE,
    fecha               TEXT NOT NULL,
    tipo                TEXT NOT NULL CHECK (tipo IN ('inicial', 'venta', 'devolucion', 'entrada', 'salida', 'ajuste')),
    cantidad            REAL NOT NULL,   -- positiva entra, negativa sale
    existencia_anterior REAL NOT NULL,
    existencia_nueva    REAL NOT NULL,
    costo_unitario      INTEGER,
    referencia          TEXT,
    usuario_id          INTEGER REFERENCES usuarios(id),
    nota                TEXT
);
CREATE INDEX IF NOT EXISTS idx_mov_inv_producto ON movimientos_inventario(producto_id, fecha);
CREATE INDEX IF NOT EXISTS idx_mov_inv_fecha ON movimientos_inventario(fecha);

CREATE TABLE IF NOT EXISTS clientes (
    id             INTEGER PRIMARY KEY,
    rut            TEXT UNIQUE,
    nombre         TEXT NOT NULL,
    telefono       TEXT,
    email          TEXT,
    direccion      TEXT,
    giro           TEXT,
    comuna         TEXT,
    ciudad         TEXT,
    limite_credito INTEGER,            -- NULL = sin límite
    saldo          INTEGER NOT NULL DEFAULT 0,  -- lo que el cliente debe
    notas          TEXT,
    activo         INTEGER NOT NULL DEFAULT 1,
    creado         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_clientes_nombre ON clientes(nombre);

-- Corte general: desde la caja principal se cierran juntos los turnos de todas las cajas.
CREATE TABLE IF NOT EXISTS cortes_generales (
    id         INTEGER PRIMARY KEY,
    fecha      TEXT NOT NULL,
    caja_id    INTEGER NOT NULL REFERENCES cajas(id),
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    nota       TEXT
);

CREATE TABLE IF NOT EXISTS turnos (
    id                INTEGER PRIMARY KEY,
    caja_id           INTEGER NOT NULL REFERENCES cajas(id),
    usuario_id        INTEGER NOT NULL REFERENCES usuarios(id),
    abierto           TEXT NOT NULL,
    cerrado           TEXT,
    fondo_inicial     INTEGER NOT NULL DEFAULT 0,
    efectivo_esperado INTEGER,
    efectivo_contado  INTEGER,
    diferencia        INTEGER,
    estado            TEXT NOT NULL DEFAULT 'abierto' CHECK (estado IN ('abierto', 'cerrado')),
    usuario_cierre_id INTEGER REFERENCES usuarios(id),
    nota              TEXT,
    corte_general_id  INTEGER REFERENCES cortes_generales(id)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_turno_abierto_por_caja ON turnos(caja_id) WHERE estado = 'abierto';
CREATE INDEX IF NOT EXISTS idx_turnos_abierto ON turnos(abierto);

CREATE TABLE IF NOT EXISTS movimientos_caja (
    id         INTEGER PRIMARY KEY,
    turno_id   INTEGER NOT NULL REFERENCES turnos(id),
    fecha      TEXT NOT NULL,
    tipo       TEXT NOT NULL CHECK (tipo IN ('entrada', 'salida')),
    monto      INTEGER NOT NULL CHECK (monto > 0),
    concepto   TEXT NOT NULL,
    usuario_id INTEGER REFERENCES usuarios(id)
);
CREATE INDEX IF NOT EXISTS idx_mov_caja_turno ON movimientos_caja(turno_id);

CREATE TABLE IF NOT EXISTS ventas (
    id              INTEGER PRIMARY KEY,
    folio           INTEGER NOT NULL UNIQUE,
    fecha           TEXT NOT NULL,
    caja_id         INTEGER NOT NULL REFERENCES cajas(id),
    turno_id        INTEGER NOT NULL REFERENCES turnos(id),
    usuario_id      INTEGER NOT NULL REFERENCES usuarios(id),
    cliente_id      INTEGER REFERENCES clientes(id),
    subtotal        INTEGER NOT NULL,   -- suma de líneas
    descuento       INTEGER NOT NULL DEFAULT 0,
    total           INTEGER NOT NULL,   -- subtotal - descuento (monto del documento)
    exento          INTEGER NOT NULL DEFAULT 0,
    neto            INTEGER NOT NULL DEFAULT 0,
    iva             INTEGER NOT NULL DEFAULT 0,
    redondeo        INTEGER NOT NULL DEFAULT 0,  -- ajuste Ley 20.956 sobre la parte en efectivo
    efectivo_recibido INTEGER NOT NULL DEFAULT 0,
    cambio          INTEGER NOT NULL DEFAULT 0,
    devuelto        INTEGER NOT NULL DEFAULT 0,  -- monto devuelto acumulado
    estado          TEXT NOT NULL DEFAULT 'completada' CHECK (estado IN ('completada', 'devuelta_parcial', 'devuelta')),
    cotizacion_id   INTEGER REFERENCES cotizaciones(id),
    nota            TEXT
);
CREATE INDEX IF NOT EXISTS idx_ventas_fecha ON ventas(fecha);
CREATE INDEX IF NOT EXISTS idx_ventas_turno ON ventas(turno_id);
CREATE INDEX IF NOT EXISTS idx_ventas_cliente ON ventas(cliente_id);

CREATE TABLE IF NOT EXISTS venta_items (
    id                INTEGER PRIMARY KEY,
    venta_id          INTEGER NOT NULL REFERENCES ventas(id) ON DELETE CASCADE,
    producto_id       INTEGER REFERENCES productos(id) ON DELETE SET NULL,  -- NULL = artículo común
    codigo            TEXT,
    descripcion       TEXT NOT NULL,
    departamento_id   INTEGER,
    cantidad          REAL NOT NULL,
    precio_unitario   INTEGER NOT NULL,
    precio_costo      INTEGER NOT NULL DEFAULT 0,
    tipo_precio       TEXT NOT NULL CHECK (tipo_precio IN ('normal', 'mayoreo', 'manual', 'comun')),
    importe           INTEGER NOT NULL,
    exento            INTEGER NOT NULL DEFAULT 0,
    cantidad_devuelta REAL NOT NULL DEFAULT 0,
    receta_id         INTEGER REFERENCES recetas_magistrales(id)  -- línea de receta magistral
);
CREATE INDEX IF NOT EXISTS idx_venta_items_venta ON venta_items(venta_id);
CREATE INDEX IF NOT EXISTS idx_venta_items_producto ON venta_items(producto_id);

CREATE TABLE IF NOT EXISTS venta_pagos (
    id       INTEGER PRIMARY KEY,
    venta_id INTEGER NOT NULL REFERENCES ventas(id) ON DELETE CASCADE,
    metodo   TEXT NOT NULL CHECK (metodo IN ('efectivo', 'debito', 'credito', 'transferencia', 'fiado')),
    monto    INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_venta_pagos_venta ON venta_pagos(venta_id);

CREATE TABLE IF NOT EXISTS devoluciones (
    id             INTEGER PRIMARY KEY,
    venta_id       INTEGER NOT NULL REFERENCES ventas(id),
    fecha          TEXT NOT NULL,
    turno_id       INTEGER NOT NULL REFERENCES turnos(id),
    usuario_id     INTEGER NOT NULL REFERENCES usuarios(id),
    monto          INTEGER NOT NULL,
    monto_efectivo INTEGER NOT NULL DEFAULT 0,  -- sale de la caja
    monto_fiado    INTEGER NOT NULL DEFAULT 0,  -- se descuenta de la deuda del cliente
    monto_otro     INTEGER NOT NULL DEFAULT 0,  -- reversa en tarjeta / transferencia, no afecta caja
    motivo         TEXT
);
CREATE INDEX IF NOT EXISTS idx_devoluciones_turno ON devoluciones(turno_id);
CREATE INDEX IF NOT EXISTS idx_devoluciones_venta ON devoluciones(venta_id);

CREATE TABLE IF NOT EXISTS devolucion_items (
    id            INTEGER PRIMARY KEY,
    devolucion_id INTEGER NOT NULL REFERENCES devoluciones(id) ON DELETE CASCADE,
    venta_item_id INTEGER NOT NULL REFERENCES venta_items(id),
    cantidad      REAL NOT NULL,
    monto         INTEGER NOT NULL
);

-- Cuenta corriente del cliente (fiado).
CREATE TABLE IF NOT EXISTS movimientos_cliente (
    id          INTEGER PRIMARY KEY,
    cliente_id  INTEGER NOT NULL REFERENCES clientes(id),
    fecha       TEXT NOT NULL,
    tipo        TEXT NOT NULL CHECK (tipo IN ('cargo', 'abono', 'devolucion')),
    monto       INTEGER NOT NULL CHECK (monto > 0),
    saldo_nuevo INTEGER NOT NULL,
    metodo      TEXT,
    venta_id    INTEGER REFERENCES ventas(id),
    turno_id    INTEGER REFERENCES turnos(id),
    usuario_id  INTEGER REFERENCES usuarios(id),
    nota        TEXT
);
CREATE INDEX IF NOT EXISTS idx_mov_cliente ON movimientos_cliente(cliente_id, fecha);
CREATE INDEX IF NOT EXISTS idx_mov_cliente_turno ON movimientos_cliente(turno_id);

CREATE TABLE IF NOT EXISTS cotizaciones (
    id             INTEGER PRIMARY KEY,
    folio          INTEGER NOT NULL UNIQUE,
    fecha          TEXT NOT NULL,
    usuario_id     INTEGER NOT NULL REFERENCES usuarios(id),
    cliente_id     INTEGER REFERENCES clientes(id),
    cliente_nombre TEXT,
    items          TEXT NOT NULL,   -- JSON con las líneas calculadas
    subtotal       INTEGER NOT NULL,
    descuento      INTEGER NOT NULL DEFAULT 0,
    total          INTEGER NOT NULL,
    estado         TEXT NOT NULL DEFAULT 'vigente' CHECK (estado IN ('vigente', 'vendida', 'cancelada')),
    nota           TEXT
);

-- ---------------------------------------------------------------------------
-- Farmacia: vademécum, principios activos y recetario magistral
-- ---------------------------------------------------------------------------

-- Un principio activo reúne su ficha de vademécum y, si se usa en fórmulas
-- magistrales, su precio neto por unidad (mg, mcg, g, ml o UI).
CREATE TABLE IF NOT EXISTS principios_activos (
    id                 INTEGER PRIMARY KEY,
    nombre             TEXT NOT NULL UNIQUE COLLATE NOCASE,
    accion_terapeutica TEXT,
    efectos_adversos   TEXT,
    contraindicaciones TEXT,
    notas              TEXT,
    unidad_receta      TEXT CHECK (unidad_receta IN ('mcg', 'mg', 'g', 'ml', 'UI')),
    precio_receta      REAL CHECK (precio_receta >= 0),  -- NULL = no se usa en el recetario
    creado             TEXT NOT NULL,
    actualizado        TEXT NOT NULL
);

-- Qué principios activos contiene cada producto (con su concentración).
CREATE TABLE IF NOT EXISTS producto_principios (
    producto_id   INTEGER NOT NULL REFERENCES productos(id) ON DELETE CASCADE,
    principio_id  INTEGER NOT NULL REFERENCES principios_activos(id),
    concentracion TEXT,
    orden         INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (producto_id, principio_id)
);
CREATE INDEX IF NOT EXISTS idx_producto_principios_pa ON producto_principios(principio_id);

-- Formas farmacéuticas del recetario: cápsulas, cremas, lociones...
-- unidad: 'unidad' (cápsula, papelillo, óvulo), 'g' o 'ml'.
CREATE TABLE IF NOT EXISTS formas_magistrales (
    id                INTEGER PRIMARY KEY,
    nombre            TEXT NOT NULL UNIQUE COLLATE NOCASE,
    unidad            TEXT NOT NULL CHECK (unidad IN ('unidad', 'g', 'ml')),
    nombre_unidad     TEXT NOT NULL,
    precio_base       REAL NOT NULL DEFAULT 0 CHECK (precio_base >= 0),    -- neto, por preparado
    precio_unidad     REAL NOT NULL DEFAULT 0 CHECK (precio_unidad >= 0),  -- neto, por cápsula/gramo/ml
    cantidad_sugerida REAL NOT NULL DEFAULT 30,
    activa            INTEGER NOT NULL DEFAULT 1
);

-- Libro de recetas magistrales: cada preparado calculado queda registrado.
CREATE TABLE IF NOT EXISTS recetas_magistrales (
    id              INTEGER PRIMARY KEY,
    folio           INTEGER NOT NULL UNIQUE,
    fecha           TEXT NOT NULL,
    usuario_id      INTEGER NOT NULL REFERENCES usuarios(id),
    forma_id        INTEGER REFERENCES formas_magistrales(id) ON DELETE SET NULL,
    forma           TEXT NOT NULL,
    unidad          TEXT NOT NULL,
    nombre_unidad   TEXT NOT NULL,
    cantidad        REAL NOT NULL,
    componentes     TEXT NOT NULL,      -- JSON con cada principio activo calculado
    precio_base     REAL NOT NULL,
    precio_unidad   REAL NOT NULL,
    suma_principios REAL NOT NULL,
    costo_unidades  REAL NOT NULL,
    neto            INTEGER NOT NULL,
    iva             INTEGER NOT NULL,
    total           INTEGER NOT NULL,
    paciente        TEXT,
    rut_paciente    TEXT,
    medico          TEXT,
    indicaciones    TEXT,
    estado          TEXT NOT NULL DEFAULT 'pendiente' CHECK (estado IN ('pendiente', 'vendida', 'anulada')),
    venta_id        INTEGER REFERENCES ventas(id)
);
CREATE INDEX IF NOT EXISTS idx_recetas_fecha ON recetas_magistrales(fecha);

-- Boleta y factura electrónica con el SII (opcional; ver neji/sii). Separada de config: tiene la firma.
CREATE TABLE IF NOT EXISTS sii_config (
    clave TEXT PRIMARY KEY,
    valor TEXT
);

-- Folios autorizados por el SII (archivo CAF), por ambiente: los de certificación no sirven en producción.
CREATE TABLE IF NOT EXISTS sii_caf (
    id         INTEGER PRIMARY KEY,
    ambiente   TEXT NOT NULL CHECK (ambiente IN ('certificacion', 'produccion')),
    tipo       INTEGER NOT NULL,
    desde      INTEGER NOT NULL,
    hasta      INTEGER NOT NULL,
    usar_desde INTEGER NOT NULL,      -- primer folio que usa Neji (si otros ya se usaron en otro sistema)
    fecha      TEXT,                  -- fecha de autorización (FA)
    xml        BLOB NOT NULL,
    cargado    TEXT NOT NULL,
    UNIQUE (ambiente, tipo, desde)
);

-- Sobres subidos al SII.
CREATE TABLE IF NOT EXISTS sii_envios (
    id        INTEGER PRIMARY KEY,
    ambiente  TEXT NOT NULL,
    boletas   INTEGER NOT NULL,       -- 1 = EnvioBOLETA (39/41), 0 = EnvioDTE
    creado    TEXT NOT NULL,
    xml       BLOB NOT NULL,
    trackid   TEXT,
    estado    TEXT NOT NULL DEFAULT 'por_enviar'
              CHECK (estado IN ('por_enviar', 'enviado', 'procesado', 'rechazado')),
    glosa     TEXT,
    intentos  INTEGER NOT NULL DEFAULT 0,
    proximo   TEXT,                   -- cuándo reintentar o volver a consultar
    revisado  TEXT,
    -- Certificación: qué es (documentos, libro, rcof) y de qué etapa (basico, exenta, simulacion, boletas,
    -- libro_ventas, libro_compras, rcof); NULL en la operación normal.
    clase     TEXT NOT NULL DEFAULT 'documentos',
    etapa     TEXT,
    detalle   TEXT                    -- JSON con lo que se envió (período del libro, casos del set...)
);
CREATE INDEX IF NOT EXISTS idx_sii_envios_estado ON sii_envios(estado);

-- Documentos tributarios electrónicos emitidos (boletas, facturas, notas de crédito).
CREATE TABLE IF NOT EXISTS sii_documentos (
    id             INTEGER PRIMARY KEY,
    ambiente       TEXT NOT NULL,
    tipo           INTEGER NOT NULL,
    folio          INTEGER NOT NULL,
    fecha          TEXT NOT NULL,     -- fecha de emisión (AAAA-MM-DD)
    emitido        TEXT NOT NULL,     -- fecha y hora
    venta_id       INTEGER REFERENCES ventas(id),
    devolucion_id  INTEGER REFERENCES devoluciones(id),
    rut_receptor   TEXT,
    razon_receptor TEXT,
    neto           INTEGER NOT NULL DEFAULT 0,
    iva            INTEGER NOT NULL DEFAULT 0,
    exento         INTEGER NOT NULL DEFAULT 0,
    total          INTEGER NOT NULL,
    xml            BLOB NOT NULL,
    ted            TEXT NOT NULL,     -- el timbre (va en el PDF417 del ticket)
    estado         TEXT NOT NULL DEFAULT 'pendiente'
                   CHECK (estado IN ('pendiente', 'enviado', 'aceptado', 'reparo', 'rechazado')),
    envio_id       INTEGER REFERENCES sii_envios(id),
    glosa          TEXT,
    -- Intercambio: la factura (y su nota de crédito) se manda por correo al cliente cuando el SII la acepta.
    correo_receptor TEXT,
    correo_estado  TEXT,              -- NULL (no corresponde), pendiente, enviado, sin_correo
    correo_glosa   TEXT,
    correo_enviado TEXT,
    caso           TEXT,              -- certificación: el caso del set de pruebas («4670590-1», «CASO-1»)
    UNIQUE (ambiente, tipo, folio)
);
CREATE INDEX IF NOT EXISTS idx_sii_documentos_venta ON sii_documentos(venta_id);
CREATE INDEX IF NOT EXISTS idx_sii_documentos_devolucion ON sii_documentos(devolucion_id);
CREATE INDEX IF NOT EXISTS idx_sii_documentos_estado ON sii_documentos(estado, envio_id);
