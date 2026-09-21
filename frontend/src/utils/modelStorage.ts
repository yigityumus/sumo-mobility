const DB_NAME = "sumo-campus-builder";
const DB_VERSION = 1;
const STORE_NAME = "campus_models";

import type { CampusModel } from "../types/campus";

function openDatabase(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);

    request.onupgradeneeded = () => {
      const database = request.result;
      if (!database.objectStoreNames.contains(STORE_NAME)) {
        const store = database.createObjectStore(STORE_NAME, { keyPath: "id" });
        store.createIndex("updatedAt", "updatedAt", { unique: false });
      }
    };

    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error("Could not open IndexedDB."));
  });
}

function runStoreOperation<T>(
  mode: IDBTransactionMode,
  operation: (store: IDBObjectStore) => IDBRequest<T>,
): Promise<T> {
  return openDatabase().then(
    (database) =>
      new Promise((resolve, reject) => {
        const transaction = database.transaction(STORE_NAME, mode);
        const store = transaction.objectStore(STORE_NAME);
        const request = operation(store);

        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error ?? new Error("IndexedDB operation failed."));
        transaction.oncomplete = () => database.close();
        transaction.onerror = () => {
          database.close();
          reject(transaction.error ?? new Error("IndexedDB transaction failed."));
        };
      }),
  );
}

export function listCampusModels() {
  return runStoreOperation<CampusModel[]>("readonly", (store) => store.getAll()).then((models) =>
    models
      .map((model) => ({
        id: model.id,
        name: model.name,
        createdAt: model.createdAt,
        updatedAt: model.updatedAt,
        buildingCount: model.buildings?.features?.length ?? 0,
        parkingCount: model.parkingAreas?.features?.length ?? 0,
        selectedBuildingCount: model.selectedBuildingIds?.length ?? 0,
        selectedParkingCount: model.selectedParkingIds?.length ?? 0,
      }))
      .sort((left, right) => String(right.updatedAt).localeCompare(String(left.updatedAt))),
  );
}

export function saveCampusModel(model: CampusModel) {
  return runStoreOperation("readwrite", (store) => store.put(model));
}

export function getCampusModel(id: string) {
  return runStoreOperation<CampusModel | undefined>("readonly", (store) => store.get(id));
}

export function deleteCampusModel(id: string) {
  return runStoreOperation("readwrite", (store) => store.delete(id));
}
