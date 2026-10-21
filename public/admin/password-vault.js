'use strict';
window.ScorecardPasswordVault = (() => {
  const ITERATIONS=600000, enc=new TextEncoder(), dec=new TextDecoder();
  const hex=b=>Array.from(new Uint8Array(b),x=>x.toString(16).padStart(2,'0')).join('');
  const unhex=s=>Uint8Array.from(String(s).match(/../g)||[],x=>parseInt(x,16));
  const randomHex=n=>{const b=new Uint8Array(n);crypto.getRandomValues(b);return hex(b)};
  async function material(password){return crypto.subtle.importKey('raw',enc.encode(password),'PBKDF2',false,['deriveBits','deriveKey'])}
  async function verifier(password,salt=randomHex(16)){const m=await material(password),bits=await crypto.subtle.deriveBits({name:'PBKDF2',hash:'SHA-256',salt:unhex(salt),iterations:ITERATIONS},m,256);return {salt,iterations:ITERATIONS,hash:hex(bits)}}
  async function verify(password,r){if(!r?.salt||!r?.hash)return false;return (await verifier(password,r.salt)).hash===r.hash}
  function generate(){return randomHex(24)}
  async function encrypt(vault,password){const salt=randomHex(16),iv=randomHex(12),m=await material(password),k=await crypto.subtle.deriveKey({name:'PBKDF2',hash:'SHA-256',salt:unhex(salt),iterations:ITERATIONS},m,{name:'AES-GCM',length:256},false,['encrypt','decrypt']),c=await crypto.subtle.encrypt({name:'AES-GCM',iv:unhex(iv)},k,enc.encode(JSON.stringify(vault)));return {version:1,algorithm:'AES-256-GCM',kdf:'PBKDF2-SHA256',iterations:ITERATIONS,salt,iv,ciphertext:hex(c)}}
  async function decrypt(r,password){const m=await material(password),k=await crypto.subtle.deriveKey({name:'PBKDF2',hash:'SHA-256',salt:unhex(r.salt),iterations:r.iterations||ITERATIONS},m,{name:'AES-GCM',length:256},false,['decrypt']),p=await crypto.subtle.decrypt({name:'AES-GCM',iv:unhex(r.iv)},k,unhex(r.ciphertext));return JSON.parse(dec.decode(p))}
  return {verifier,verify,generate,encrypt,decrypt};
})();
