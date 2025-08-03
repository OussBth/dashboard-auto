import time
import subprocess
from proxmoxer import ProxmoxAPI

# ==============================================================================
# ----------------------------- CONFIGURATION ----------------------------------
# ==============================================================================
# Informations de connexion à l'API Proxmox
PROXMOX_HOST = '192.168.8.149'  # Remplacez par l'IP de votre Proxmox
PROXMOX_USER = 'api_user@pam'          # Ex: 'root@pam' ou 'api-user@pve'
PROXMOX_TOKEN_NAME = 'Token_test'
PROXMOX_TOKEN_VALUE = '3a310f2d-1271-47b4-aa12-b04d582efd61'

# Paramètres de votre infrastructure Proxmox
NODE_NAME = 'pve'                   # Le nom de votre nœud Proxmox
TEMPLATE_ID = 100                   # L'ID de votre template Debian 12
STORAGE_POOL = 'vm-et-ct'          # Le stockage pour le disque du CT

# Paramètres du nouveau conteneur
NEW_CT_ID = 200                     # ID du nouveau conteneur à créer
NEW_HOSTNAME = 'webserver-01'

# Paramètres Ansible
ANSIBLE_PLAYBOOK = 'deploy_nginx.yml' # Le chemin vers votre playbook
# ==============================================================================


def run_ansible(ip_address):
    """Crée un inventaire temporaire et lance le playbook Ansible."""
    print(f"--- [Ansible] Lancement de la configuration sur {ip_address} ---")
    
    # Crée un fichier d'inventaire simple pour cette exécution
    inventory_content = f"[webserver]\n{ip_address} ansible_user=root\n"
    with open("temp_inventory.ini", "w") as f:
        f.write(inventory_content)

    # Commande pour lancer Ansible
    command = [
        "ansible-playbook",
        "-i", "temp_inventory.ini",
        ANSIBLE_PLAYBOOK,
        "--ssh-common-args", "-o StrictHostKeyChecking=no" # Ignore la vérification de la clé SSH pour le premier contact
    ]

    try:
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        print("--- [Ansible] Playbook exécuté avec succès ! ---")
        print(result.stdout)
    except subprocess.CalledProcessError as e:
        print("--- [Ansible] ERREUR lors de l'exécution du playbook ---")
        print(e.stderr)

def main():
    """Fonction principale pour orchestrer le déploiement."""
    try:
        print("--- [Proxmox] Connexion à l'API... ---")
        proxmox = ProxmoxAPI(
            PROXMOX_HOST,
            user=PROXMOX_USER,
            token_name=PROXMOX_TOKEN_NAME,
            token_value=PROXMOX_TOKEN_VALUE,
            verify_ssl=False  # Mettre à True en production avec un certificat valide
        )
    except Exception as e:
        print(f"Erreur de connexion à l'API Proxmox : {e}")
        return

    node = proxmox.nodes(NODE_NAME)
    
    # --- Étape 1: Cloner le template ---
    print(f"--- [Proxmox] Lancement du clonage du template {TEMPLATE_ID} vers le nouveau CT {NEW_CT_ID} ---")
    try:
        task_id = node.lxc(TEMPLATE_ID).clone.post(newid=NEW_CT_ID, hostname=NEW_HOSTNAME, storage=STORAGE_POOL, full=1)
        # On attend la fin de la tâche de clonage
        while node.tasks(task_id).status.get()['status'] == 'running':
             time.sleep(2)
        print(f"--- [Proxmox] Clonage terminé avec succès ! ---")
    except Exception as e:
        print(f"Erreur lors du clonage : {e}")
        return

    # --- Étape 2: Démarrer le conteneur et attendre l'IP ---
    print(f"--- [Proxmox] Démarrage du conteneur {NEW_CT_ID}... ---")
    node.lxc(NEW_CT_ID).status.start.post()
    time.sleep(5) # Laisser un peu de temps au conteneur pour démarrer

    print("--- [Proxmox] Récupération de l'adresse IP (méthode compatible)... ---")
    container_ip = None
    for _ in range(20): # On essaie pendant 40 secondes max
        try:
            # On utilise l'API 'status/current' qui est compatible avec plus de versions
            status = node.lxc(NEW_CT_ID).status.current.get()
            # On vérifie si la clé 'ip' existe et a une valeur
            if status.get('ip'):
                container_ip = status['ip']
                print(f"--- [Proxmox] Adresse IP trouvée : {container_ip} ---")
                break
        except Exception as e:
            print(f"Tentative de récupération de l'IP échouée : {e}")

        if container_ip:
            break
        
        print("IP non trouvée, nouvelle tentative dans 3 secondes...")
        time.sleep(3)
    
    if not container_ip:
        print("--- ERREUR : Impossible de récupérer l'adresse IP du conteneur. ---")
        return

    # --- Étape 3: Lancer Ansible ---
    # Attendre un peu plus pour être sûr que le serveur SSH est bien démarré
    print("--- Attente de 10 secondes pour la stabilisation du service SSH... ---")
    time.sleep(10)
    run_ansible(container_ip)

if __name__ == "__main__":
    main()