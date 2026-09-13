import { useState, useEffect } from 'react';
import { Users, Plus, Trash2, ShieldAlert } from 'lucide-react';
import { config } from '../../../config';

export function TeamManagementPanel() {
  
  const [users, setUsers] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [isAdding, setIsAdding] = useState(false);
  
  const [newUser, setNewUser] = useState({
    email: '',
    full_name: '',
    job_title: '',
    password: '',
    role: 'employee'
  });

  const fetchUsers = async () => {
    try {
      const res = await fetch(`${config.API_BASE_URL}/tenant/users`, {
        headers: { 'Authorization': "" }
      });
      if (res.ok) {
        setUsers(await res.json());
      }
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchUsers();
  }, []);

  const handleAddUser = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    try {
      const res = await fetch(`${config.API_BASE_URL}/tenant/users`, {
        method: 'POST',
        headers: { 
          'Authorization': "",
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(newUser)
      });
      
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || 'Failed to create user');
      }
      
      setIsAdding(false);
      setNewUser({ email: '', full_name: '', job_title: '', password: '', role: 'employee' });
      fetchUsers();
    } catch (err: any) {
      setError(err.message);
    }
  };

  const handleDeleteUser = async (id: string) => {
    if (!confirm('Are you sure you want to remove this employee?')) return;
    try {
      const res = await fetch(`${config.API_BASE_URL}/tenant/users/${id}`, {
        method: 'DELETE',
        headers: { 'Authorization': "" }
      });
      if (res.ok) fetchUsers();
      else {
        const data = await res.json();
        alert(data.detail || 'Failed to delete user');
      }
    } catch (err) {
      console.error(err);
    }
  };

  if (loading) return <div className="p-8 text-center text-slate-500 animate-pulse">Loading Team...</div>;

  return (
    <div className="bg-slate-900/50 border border-slate-800 rounded-2xl p-8 shadow-xl">
      <div className="flex items-center justify-between mb-8 pb-6 border-b border-slate-800">
        <div className="flex items-center gap-4">
          <div className="bg-indigo-500/20 p-4 rounded-xl text-indigo-400">
            <Users size={24} />
          </div>
          <div>
            <h2 className="text-xl font-semibold text-white">Team Management</h2>
            <p className="text-sm text-slate-400">Manage employees and their access to the Aether ITSM agent.</p>
          </div>
        </div>
        {!isAdding && (
          <button 
            onClick={() => setIsAdding(true)}
            className="bg-indigo-600 hover:bg-indigo-500 text-white px-4 py-2 rounded-lg text-sm transition-colors flex items-center gap-2"
          >
            <Plus size={16} /> Add Employee
          </button>
        )}
      </div>

      {error && (
        <div className="mb-6 p-4 bg-rose-500/10 border border-rose-500/20 rounded-xl flex items-center gap-3 text-rose-400 text-sm">
          <ShieldAlert size={18} />
          {error}
        </div>
      )}

      {isAdding && (
        <form onSubmit={handleAddUser} className="mb-8 bg-slate-950 border border-slate-800 p-6 rounded-xl space-y-4">
          <h3 className="text-sm font-medium text-slate-300 mb-4">Invite New Employee</h3>
          
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1">
              <label className="text-xs text-slate-400">Full Name</label>
              <div className="relative">
                <input required type="text" value={newUser.full_name} onChange={e => setNewUser({...newUser, full_name: e.target.value})} className="w-full bg-slate-900 border border-slate-700 rounded-lg pl-3 pr-3 py-2 text-sm text-white" />
              </div>
            </div>
            <div className="space-y-1">
              <label className="text-xs text-slate-400">Email</label>
              <div className="relative">
                <input required type="email" value={newUser.email} onChange={e => setNewUser({...newUser, email: e.target.value})} className="w-full bg-slate-900 border border-slate-700 rounded-lg pl-3 pr-3 py-2 text-sm text-white" />
              </div>
            </div>
            <div className="space-y-1">
              <label className="text-xs text-slate-400">Job Title</label>
              <div className="relative">
                <input type="text" value={newUser.job_title} onChange={e => setNewUser({...newUser, job_title: e.target.value})} className="w-full bg-slate-900 border border-slate-700 rounded-lg pl-3 pr-3 py-2 text-sm text-white" />
              </div>
            </div>
            <div className="space-y-1">
              <label className="text-xs text-slate-400">Temporary Password</label>
              <div className="relative">
                <input required type="password" value={newUser.password} onChange={e => setNewUser({...newUser, password: e.target.value})} className="w-full bg-slate-900 border border-slate-700 rounded-lg pl-3 pr-3 py-2 text-sm text-white" />
              </div>
            </div>
          </div>
          
          <div className="flex justify-end gap-2 pt-4">
            <button type="button" onClick={() => setIsAdding(false)} className="px-4 py-2 text-sm text-slate-400 hover:text-white transition-colors">Cancel</button>
            <button type="submit" className="px-4 py-2 text-sm bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg transition-colors">Create User</button>
          </div>
        </form>
      )}

      <div className="overflow-x-auto">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="border-b border-slate-800 text-sm font-medium text-slate-500">
              <th className="pb-3 px-4 font-medium">Employee</th>
              <th className="pb-3 px-4 font-medium">Role</th>
              <th className="pb-3 px-4 font-medium">Joined</th>
              <th className="pb-3 px-4 font-medium text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="text-sm">
            {users.map(u => (
              <tr key={u.id} className="border-b border-slate-800/50 hover:bg-slate-800/20 transition-colors">
                <td className="py-4 px-4">
                  <div className="flex items-center gap-3">
                    <div className="w-8 h-8 rounded-full bg-indigo-500/20 flex items-center justify-center text-indigo-400 font-medium">
                      {u.full_name.charAt(0)}
                    </div>
                    <div>
                      <p className="text-slate-200 font-medium">{u.full_name}</p>
                      <p className="text-slate-500 text-xs">{u.email}</p>
                    </div>
                  </div>
                </td>
                <td className="py-4 px-4 text-slate-400">
                  <span className={`px-2.5 py-1 rounded-full text-xs font-medium ${
                    u.role === 'admin' || u.role === 'superadmin' ? 'bg-amber-500/10 text-amber-400 border border-amber-500/20' : 'bg-slate-800 text-slate-300'
                  }`}>
                    {u.role}
                  </span>
                </td>
                <td className="py-4 px-4 text-slate-500">
                  {new Date(u.created_at).toLocaleDateString()}
                </td>
                <td className="py-4 px-4 text-right">
                  <button 
                    onClick={() => handleDeleteUser(u.id)}
                    className="text-slate-500 hover:text-rose-400 p-2 rounded-lg hover:bg-rose-500/10 transition-colors"
                  >
                    <Trash2 size={16} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
